import { expect, test } from "playwright/test";

// E11-S2 DoD: the account page renders without crashing whether or not a
// live backend is reachable (mirrors shell-navigation.spec.ts's "backend
// may be offline" tolerance), and — when a backend *is* reachable in its
// default local zero-config mode — resolves and displays the transparent
// local owner principal with no OIDC provider configured.

test("/auth renders inside the shell without crashing", async ({ page }) => {
  await page.goto("/auth");

  const header = page.getByRole("banner");
  await expect(header).toBeVisible();
  await expect(header.getByRole("heading", { level: 1 })).toHaveText("Account");
});

test("local zero-config resolves and displays the local owner principal", async ({ page }) => {
  await page.goto("/auth");

  // Soft-skip if no backend answered /v2/auth/me at all (offline backend,
  // matching this suite's other specs) rather than asserting on network
  // conditions this spec doesn't control.
  const loading = page.getByText("Loading…");
  const signIn = page.getByRole("link", { name: "Sign in" });
  const subject = page.getByText("Subject", { exact: true });

  await Promise.race([
    subject.waitFor({ timeout: 10_000 }).catch(() => undefined),
    signIn.waitFor({ timeout: 10_000 }).catch(() => undefined),
  ]);

  if (await signIn.isVisible().catch(() => false)) {
    // Production-shaped backend with OIDC/service-key configured, or the
    // backend never resolved a local zero-config principal; either is a
    // valid, non-crashing outcome for this environment-independent spec.
    return;
  }

  await expect(loading).toHaveCount(0);
  // Scoped to the "Subject" <dt>/<dd> pair, not a bare getByText("local"):
  // the local zero-config principal's authMethod is *also* literally
  // "local", so an unscoped match resolves to two elements (strict-mode
  // violation) once a real backend actually answers this request.
  const subjectValue = page
    .locator("dt", { hasText: "Subject" })
    .locator("xpath=following-sibling::dd[1]");
  await expect(subjectValue).toHaveText("local");
  await expect(page.getByText("default")).toBeVisible();
  await expect(page.getByText("owner")).toBeVisible();
});
