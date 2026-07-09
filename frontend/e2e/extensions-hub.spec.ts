import { expect, test, type Page } from "playwright/test";

// E17-S5 DoD: an e2e spec covering the Extensions hub — the unified home
// for Agents, Skills, Plugins, and MCP exposures (ADR-012 §5). The backend
// may be offline in CI, so every `/v2/extensions*` request is intercepted
// with `page.route` and answered from an in-memory fixture; this exercises
// the real component/network wiring (fetch, tabs, toggle, create/edit
// modal) without requiring a live control plane.

type ExtensionItem = {
  kind: "agent" | "skill" | "plugin" | "mcp";
  id: string;
  name: string;
  enabled: boolean;
  pluginId: string | null;
  detail: Record<string, unknown>;
};

const ITEMS: ExtensionItem[] = [
  {
    kind: "agent",
    id: "reviewer",
    name: "Reviewer",
    enabled: true,
    pluginId: null,
    detail: { version: "1.2.0", capabilities: ["code-review", "security"] },
  },
  {
    kind: "agent",
    id: "planner",
    name: "Planner",
    enabled: false,
    pluginId: null,
    detail: { version: "1.0.0", capabilities: ["planning"] },
  },
  {
    kind: "skill",
    id: "summarize-diff",
    name: "Summarize diff",
    enabled: true,
    pluginId: "core-skills",
    detail: { version: "0.4.1", triggers: ["patch.created"] },
  },
  {
    kind: "plugin",
    id: "github-integration",
    name: "GitHub integration",
    enabled: false,
    pluginId: null,
    detail: { version: "2.0.0", extensionPoints: ["patch.review"] },
  },
];

/**
 * Intercept every `/v2/extensions*` request the hub makes and answer it
 * from the in-memory {@link ITEMS} fixture, mutating enabled state in place
 * so enable/disable actions and refetches stay consistent within a test.
 *
 * @param page - The Playwright page to install routing on.
 */
async function mockExtensionsApi(page: Page): Promise<void> {
  // Registered first so the more specific routes below (last-registered-wins
  // in Playwright) take priority for the agent-CRUD and enable/disable
  // paths; this one only ever matches the plain catalog list request.
  await page.route("**/v2/extensions*", async (route) => {
    await route.fulfill({
      json: {
        schemaVersion: "1.0",
        items: ITEMS,
        page: { limit: 500, offset: 0, total: ITEMS.length },
      },
    });
  });

  await page.route("**/v2/extensions/agents/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const agentId = decodeURIComponent(url.pathname.split("/").pop() ?? "");
    const item = ITEMS.find((candidate) => candidate.kind === "agent" && candidate.id === agentId);

    if (request.method() === "PUT") {
      const payload = request.postDataJSON() as {
        displayName?: string;
        model?: string;
        allowedTools?: string[];
        systemPrompt?: string;
      };
      const resolved = item ?? {
        kind: "agent" as const,
        id: agentId,
        name: agentId,
        enabled: true,
        pluginId: null,
        detail: {},
      };
      if (!item) {
        ITEMS.push(resolved);
      }
      resolved.name = payload.displayName ?? resolved.name;
      await route.fulfill({
        json: {
          schemaVersion: "1.0",
          item: resolved,
          systemPrompt: payload.systemPrompt ?? "",
          model: payload.model ?? "",
          allowedTools: payload.allowedTools ?? [],
        },
      });
      return;
    }

    await route.fulfill({
      json: {
        schemaVersion: "1.0",
        item: item ?? ITEMS[0],
        systemPrompt: "You are a meticulous code reviewer.",
        model: "claude-opus-4",
        allowedTools: ["read_file", "grep"],
      },
    });
  });

  await page.route(/\/v2\/extensions\/[^/]+\/[^/]+\/(enable|disable)/, async (route) => {
    const url = new URL(route.request().url());
    const [, , kind, id, action] = url.pathname.split("/");
    const item = ITEMS.find((candidate) => candidate.kind === kind && candidate.id === id);
    if (item) {
      item.enabled = action === "enable";
    }
    await route.fulfill({
      json: { schemaVersion: "1.0", item: item ?? ITEMS[0] },
    });
  });
}

test.describe("Extensions hub", () => {
  test.beforeEach(async ({ page }) => {
    await mockExtensionsApi(page);
  });

  test("legacy /agents and /skills routes redirect to /extensions", async ({ page }) => {
    await page.goto("/agents");
    await expect(page).toHaveURL(/\/extensions$/);

    await page.goto("/skills");
    await expect(page).toHaveURL(/\/extensions$/);
  });

  test("tabs show live counts and switch between kinds", async ({ page }) => {
    await page.goto("/extensions");

    const tabs = page.getByRole("tablist");
    await expect(tabs.getByRole("tab", { name: /Agents \(2\)/ })).toBeVisible();
    await expect(tabs.getByRole("tab", { name: /Skills \(1\)/ })).toBeVisible();
    await expect(tabs.getByRole("tab", { name: /Plugins \(1\)/ })).toBeVisible();
    await expect(tabs.getByRole("tab", { name: /MCP \(0\)/ })).toBeVisible();

    // Agents tab is active by default.
    await expect(page.locator('[role="button"]').filter({ hasText: "Reviewer" })).toBeVisible();
    await expect(page.locator('[role="button"]').filter({ hasText: "Planner" })).toBeVisible();

    await tabs.getByRole("tab", { name: /Skills/ }).click();
    await expect(page.locator('[role="button"]').filter({ hasText: "Summarize diff" })).toBeVisible();
    await expect(page.locator('[role="button"]').filter({ hasText: "Reviewer" })).toHaveCount(0);
  });

  test("toggling a card's switch enables or disables it", async ({ page }) => {
    await page.goto("/extensions");

    const plannerCard = page.locator('[role="button"]').filter({ hasText: "Planner" });
    const plannerToggle = plannerCard.getByRole("switch");
    await expect(plannerToggle).toHaveAttribute("aria-checked", "false");

    await plannerToggle.click();
    await expect(plannerToggle).toHaveAttribute("aria-checked", "true");
    await expect(plannerCard.getByText("Active")).toBeVisible();
  });

  test("create agent modal saves a new agent and refreshes the catalog", async ({ page }) => {
    await page.goto("/extensions");

    await page.getByRole("button", { name: "Create agent" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Create agent" })).toBeVisible();

    await dialog.getByLabel("Agent id").fill("team/triager");
    await dialog.getByLabel("Model").fill("claude-sonnet-5");
    await dialog.getByLabel("Agent instruction (system prompt)").fill("Triage incoming issues.");
    await dialog.getByRole("button", { name: "Create agent" }).click();

    await expect(dialog).toHaveCount(0);
    await expect(
      page.getByRole("tablist").getByRole("tab", { name: /Agents \(3\)/ })
    ).toBeVisible();
    await expect(page.locator('[role="button"]').filter({ hasText: "team/triager" })).toBeVisible();
  });

  test("clicking a skill card opens its read-only detail dialog", async ({ page }) => {
    await page.goto("/extensions");
    await page.getByRole("tablist").getByRole("tab", { name: /Skills/ }).click();

    await page.locator('[role="button"]').filter({ hasText: "Summarize diff" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Summarize diff" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Disable" })).toBeVisible();

    await dialog.getByRole("button", { name: "Disable" }).click();
    await expect(dialog).toHaveCount(0);
  });
});
