import { expect, test } from "playwright/test";

// E17-S4 DoD: e2e coverage for the Sessions list and Config screens.
//
// Both screens are API-first (only ever call /v2/* endpoints). Rather than
// depending on a live backend being seeded with fixture data, these specs
// intercept the browser's requests to http://localhost:8000/v2/** with
// page.route and serve deterministic fixtures — so the tests assert real
// rendered state (DOM, ARIA, links) driven by the actual page components,
// without flaking on backend availability or data ordering.

const API_ORIGIN = "http://localhost:8000";

test.describe("Sessions screen", () => {
  test("renders goal, id, run count, relative time, status, and reopen-as-chat link", async ({
    page,
  }) => {
    const lastRunAt = new Date(Date.now() - 5 * 60 * 1000).toISOString();

    await page.route(`${API_ORIGIN}/v2/sessions?*`, async (route) => {
      await route.fulfill({
        json: {
          schemaVersion: "1",
          items: [
            {
              schemaVersion: "1",
              session_id: "session-e2e-1",
              goal: "Bootstrap the ingestion pipeline",
              plan: [],
              status: "running",
              history: [],
            },
          ],
          page: { limit: 100, offset: 0, total: 1 },
        },
      });
    });

    await page.route(`${API_ORIGIN}/v2/sessions/session-e2e-1/runs?*`, async (route) => {
      await route.fulfill({
        json: {
          schemaVersion: "1",
          items: [
            {
              schemaVersion: "1",
              run_id: "run-1",
              session_id: "session-e2e-1",
              status: "running",
              run_type: "chat",
              current_state: "running",
              trigger_message: "go",
              created_at: lastRunAt,
              results: [],
              steps: [],
            },
          ],
          page: { limit: 1, offset: 0, total: 3 },
        },
      });
    });

    await page.goto("/sessions");

    const row = page.getByRole("row", { name: /Bootstrap the ingestion pipeline/ });
    await expect(row).toBeVisible();

    // Goal links to the session detail screen.
    await expect(row.getByRole("link", { name: "Bootstrap the ingestion pipeline" })).toHaveAttribute(
      "href",
      "/sessions/session-e2e-1"
    );

    // Session id, run count (from page.total), and relative last-run time.
    await expect(row.getByText("session-e2e-1", { exact: true })).toBeVisible();
    await expect(row.getByText("3", { exact: true })).toBeVisible();
    await expect(row.getByText("5m ago", { exact: true })).toBeVisible();

    // Status is conveyed via a visible text label, not color alone.
    await expect(row.getByText("running", { exact: true })).toBeVisible();

    // Reopen-as-chat hands off to the chat screen via ?sessionId=.
    await expect(row.getByRole("link", { name: "Open chat" })).toHaveAttribute(
      "href",
      "/?sessionId=session-e2e-1"
    );
  });

  test("shows an empty-state message when no sessions match the search", async ({ page }) => {
    await page.route(`${API_ORIGIN}/v2/sessions?*`, async (route) => {
      await route.fulfill({
        json: {
          schemaVersion: "1",
          items: [
            {
              schemaVersion: "1",
              session_id: "session-e2e-2",
              goal: "Add pgvector search",
              plan: [],
              status: "completed",
              history: [],
            },
          ],
          page: { limit: 100, offset: 0, total: 1 },
        },
      });
    });
    await page.route(`${API_ORIGIN}/v2/sessions/session-e2e-2/runs?*`, async (route) => {
      await route.fulfill({
        json: {
          schemaVersion: "1",
          items: [],
          page: { limit: 1, offset: 0, total: 0 },
        },
      });
    });

    await page.goto("/sessions");
    await expect(page.getByText("Add pgvector search")).toBeVisible();

    await page.getByLabel("Search sessions").fill("no such session");
    await expect(page.getByText("No sessions match the current search.")).toBeVisible();
  });
});

test.describe("Config screen", () => {
  const baseConfig = {
    version: 1,
    llm: {
      provider: "stub",
      model: "deterministic-stub",
      base_url: "",
      temperature: 0.2,
      api_key: "",
    },
    repository: {
      project_root: "/workspace/autodev",
      repository_label: "autodev",
      default_goal: "Ship the next increment",
    },
  };

  const instructions = {
    config_path: "~/.autodev/config.json",
    config_file_example: "{}",
    env_file_example: "AUTODEV_LLM_PROVIDER=stub",
    notes: ["Environment variables override the config file."],
  };

  test.beforeEach(async ({ page }) => {
    await page.route(`${API_ORIGIN}/v2/config`, async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          json: { schemaVersion: "1", config: baseConfig, instructions },
        });
        return;
      }
      // PUT: echo back whatever the client submitted, as the real endpoint would.
      const body = JSON.parse(route.request().postData() ?? "{}");
      await route.fulfill({
        json: { schemaVersion: "1", config: body.config, instructions },
      });
    });

    await page.route(`${API_ORIGIN}/v2/provider-config/status`, async (route) => {
      await route.fulfill({
        json: {
          schemaVersion: "1",
          name: "stub",
          model: "deterministic-stub",
          configured: true,
          healthy: true,
        },
      });
    });
  });

  test("selecting a provider auto-fills its default model", async ({ page }) => {
    await page.goto("/config");

    const selector = page.getByRole("radiogroup", { name: "LLM provider" });
    await expect(selector).toBeVisible();

    const stubPill = selector.getByRole("radio", { name: "Stub (offline)" });
    const ollamaPill = selector.getByRole("radio", { name: "Ollama" });
    await expect(stubPill).toHaveAttribute("aria-checked", "true");
    await expect(ollamaPill).toHaveAttribute("aria-checked", "false");

    await ollamaPill.click();

    await expect(ollamaPill).toHaveAttribute("aria-checked", "true");
    await expect(stubPill).toHaveAttribute("aria-checked", "false");
    await expect(page.getByLabel("Model")).toHaveValue("qwen2.5-coder:14b");
  });

  test("disables save while a required field is empty and re-enables once fixed", async ({
    page,
  }) => {
    await page.goto("/config");

    const saveButton = page.getByRole("button", { name: "Save configuration" });
    await expect(saveButton).toBeEnabled();

    const modelField = page.getByLabel("Model");
    await modelField.fill("");
    await expect(saveButton).toBeDisabled();

    await modelField.fill("deterministic-stub");
    await expect(saveButton).toBeEnabled();
  });

  test("saves the configuration and shows optimistic success feedback", async ({ page }) => {
    await page.goto("/config");

    await page.getByLabel("Project directory").fill("/workspace/autodev-renamed");
    await page.getByRole("button", { name: "Save configuration" }).click();

    await expect(page.getByRole("status").filter({ hasText: "Configuration saved" })).toBeVisible();
    await expect(page.getByLabel("Project directory")).toHaveValue("/workspace/autodev-renamed");
  });
});
