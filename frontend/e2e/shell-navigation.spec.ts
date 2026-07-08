import { expect, test } from "playwright/test";

// E15-S2 DoD: e2e navigation test across all routes in the new shell.
//
// Every frontend/app route must render inside the three-region shell:
// sidebar rail (aside[aria-label="Primary"]), 64px contextual header
// (role=banner), and the routed content inside main#shell-main-content.
// The backend may be offline while these run — the shell fails softly
// (badge-less nav, "unconfigured" provider card), so none of these
// assertions depend on /v2 API data.

/** Every navigable route and the nav item expected to be highlighted. */
const ROUTES: ReadonlyArray<{ path: string; navLabel: string }> = [
  { path: "/", navLabel: "Chat" },
  { path: "/plans", navLabel: "Plans" },
  { path: "/patches", navLabel: "Patches" },
  { path: "/flows", navLabel: "Flows" },
  { path: "/sessions", navLabel: "Sessions" },
  { path: "/config", navLabel: "Config" },
  { path: "/agents", navLabel: "Agents" },
  { path: "/skills", navLabel: "Skills" },
  { path: "/panels", navLabel: "Panels" },
];

for (const { path, navLabel } of ROUTES) {
  test(`${path} renders inside the three-region shell (active nav: ${navLabel})`, async ({
    page,
  }) => {
    await page.goto(path);

    // Region 1: sidebar rail with both nav groups.
    const rail = page.locator('aside[aria-label="Primary"]');
    await expect(rail).toBeVisible();
    await expect(rail.getByRole("navigation", { name: "Workspace" })).toBeVisible();
    await expect(rail.getByRole("navigation", { name: "Legacy" })).toBeVisible();

    // Region 2: contextual header with a published title and the primary action.
    const header = page.getByRole("banner");
    await expect(header).toBeVisible();
    await expect(header.getByRole("heading", { level: 1 })).not.toBeEmpty();
    await expect(header.getByRole("button", { name: "New session" })).toBeVisible();

    // Region 3 host: the routed content lives in the skip-link target.
    await expect(page.locator("main#shell-main-content")).toBeVisible();

    // Active-route highlighting via aria-current.
    const active = rail.locator('a[aria-current="page"]');
    await expect(active).toHaveCount(1);
    await expect(active).toContainText(navLabel);
  });
}

test("execution panel opens from the header toggle and dismisses with Escape", async ({
  page,
}) => {
  await page.goto("/plans");

  const toggle = page.getByRole("banner").getByRole("button", { name: "Execution" });
  const panel = page.getByRole("complementary", { name: "Execution panel" });

  await expect(panel).toHaveCount(0);
  await expect(toggle).toHaveAttribute("aria-pressed", "false");

  await toggle.click();
  await expect(panel).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");

  // Panel open state persists across client-side navigation (CNF).
  await page.locator('aside[aria-label="Primary"]').getByRole("link", { name: "Patches" }).click();
  await expect(page).toHaveURL(/\/patches$/);
  await expect(panel).toBeVisible();

  // Keyboard dismissal (CF).
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
});

test("execution panel close button dismisses the panel", async ({ page }) => {
  await page.goto("/config");

  await page.getByRole("banner").getByRole("button", { name: "Execution" }).click();
  const panel = page.getByRole("complementary", { name: "Execution panel" });
  await expect(panel).toBeVisible();

  await panel.getByRole("button", { name: "Close execution panel" }).click();
  await expect(panel).toHaveCount(0);
});

test("skip link is the first tab stop and targets the main region", async ({ page }) => {
  await page.goto("/");

  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  await expect(skipLink).toBeFocused();

  await page.keyboard.press("Enter");
  await expect(page.locator("main#shell-main-content")).toBeFocused();
});
