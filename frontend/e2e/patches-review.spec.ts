import { expect, test, type Page } from "playwright/test";

// E17-S3 DoD: e2e coverage of the Patches review screen's diff -> edit ->
// apply flow. The backend is mocked via page.route (no live control plane
// in e2e, per playwright.config.ts), matching shell-navigation.spec.ts's
// approach of not depending on a running API.

const SESSION_ID = "session-e2e-1";
const PATCH_ID = "patch-e2e-1";
const FILE_PATH = "backend/api/middleware/rate_limit.py";

const SAMPLE_DIFF = [
  "--- a/backend/api/middleware/rate_limit.py",
  "+++ b/backend/api/middleware/rate_limit.py",
  "@@ -1,3 +1,4 @@",
  " import time",
  "+import logging",
  "-DEFAULT_LIMIT = 10",
  "+DEFAULT_LIMIT = 100",
  " ",
].join("\n");

/** Register mocked `/v2` patch-review responses for the given page. */
async function mockPatchReviewApi(page: Page, options: { status?: "proposed" | "applied" } = {}) {
  const status = options.status ?? "proposed";

  await page.route("**/v2/sessions?*", async (route) => {
    await route.fulfill({
      json: {
        schemaVersion: "1.0",
        items: [
          {
            schemaVersion: "1.0",
            session_id: SESSION_ID,
            goal: "Add rate limiting",
            plan: [],
            status: "active",
            history: [],
          },
        ],
        page: { limit: 100, offset: 0, total: 1 },
      },
    });
  });

  await page.route(`**/v2/sessions/${SESSION_ID}/patches?*`, async (route) => {
    await route.fulfill({
      json: {
        schemaVersion: "1.0",
        session_id: SESSION_ID,
        items: [
          {
            schemaVersion: "1.0",
            patch_id: PATCH_ID,
            path: FILE_PATH,
            status,
            added_lines: 2,
            removed_lines: 1,
          },
        ],
        page: { limit: 100, offset: 0, total: 1 },
      },
    });
  });

  await page.route(`**/v2/sessions/${SESSION_ID}/patches/${PATCH_ID}`, async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      json: {
        schemaVersion: "1.0",
        patch_id: PATCH_ID,
        session_id: SESSION_ID,
        path: FILE_PATH,
        status,
        original: "import time\nDEFAULT_LIMIT = 10\n",
        updated: "import time\nimport logging\nDEFAULT_LIMIT = 100\n",
        diff: SAMPLE_DIFF,
        added_lines: 2,
        removed_lines: 1,
        audit: [],
      },
    });
  });

  await page.route(`**/v2/sessions/${SESSION_ID}/patches/${PATCH_ID}/apply`, async (route) => {
    await route.fulfill({
      json: {
        schemaVersion: "1.0",
        patch_id: PATCH_ID,
        session_id: SESSION_ID,
        path: FILE_PATH,
        applied: true,
        dry_run: false,
        message: "Applied to disk.",
        audit: { actor: "operator", timestamp: "2026-07-08T00:00:00Z", action: "apply", result: "ok", message: "Applied" },
      },
    });
  });

  await page.route(`**/v2/sessions/${SESSION_ID}/patches/${PATCH_ID}/discard`, async (route) => {
    await route.fulfill({
      json: {
        schemaVersion: "1.0",
        patch_id: PATCH_ID,
        session_id: SESSION_ID,
        path: FILE_PATH,
        status: "discarded",
        original: "import time\nDEFAULT_LIMIT = 10\n",
        updated: "import time\nimport logging\nDEFAULT_LIMIT = 100\n",
        diff: SAMPLE_DIFF,
        added_lines: 2,
        removed_lines: 1,
        audit: [],
      },
    });
  });
}

test("patches review: shows the file panel and unified diff by default", async ({ page }) => {
  await mockPatchReviewApi(page);
  await page.goto("/patches");

  await expect(page.getByRole("navigation", { name: "Changed files" })).toBeVisible();
  await expect(page.getByRole("button", { name: /rate_limit\.py/ })).toBeVisible();

  const diffTable = page.getByRole("table", { name: "Unified diff" });
  await expect(diffTable).toBeVisible();
  await expect(diffTable).toContainText("import logging");
  await expect(diffTable).toContainText("DEFAULT_LIMIT = 100");

  await expect(page.getByText("Dry-run · nothing written yet")).toBeVisible();
});

test("patches review: switching to Edit preserves manual edits, then Apply writes them", async ({
  page,
}) => {
  await mockPatchReviewApi(page);
  await page.goto("/patches");

  await page.getByRole("tab", { name: "Edit" }).click();
  const editor = page.getByRole("textbox", { name: /Edit the resulting content/ });
  await expect(editor).toHaveValue(/DEFAULT_LIMIT = 100/);

  await editor.fill("import time\nimport logging\nDEFAULT_LIMIT = 250\n");

  // Switching segments must not lose the in-progress edit (CNF).
  await page.getByRole("tab", { name: "Diff" }).click();
  await page.getByRole("tab", { name: "Edit" }).click();
  await expect(editor).toHaveValue(/DEFAULT_LIMIT = 250/);

  let overrideCalled = false;
  await page.route(`**/v2/sessions/${SESSION_ID}/patches/${PATCH_ID}/content`, async (route) => {
    overrideCalled = true;
    await route.fulfill({
      json: {
        schemaVersion: "1.0",
        patch_id: PATCH_ID,
        session_id: SESSION_ID,
        path: FILE_PATH,
        status: "proposed",
        original: "import time\nDEFAULT_LIMIT = 10\n",
        updated: "import time\nimport logging\nDEFAULT_LIMIT = 250\n",
        diff: SAMPLE_DIFF,
        added_lines: 2,
        removed_lines: 1,
        audit: [],
      },
    });
  });

  await page.getByRole("button", { name: "Apply approved patch" }).click();
  await expect(page.getByText("Patch applied")).toBeVisible();
  expect(overrideCalled).toBe(true);
});

test("patches review: Discard sends the patch to the discard endpoint", async ({ page }) => {
  await mockPatchReviewApi(page);
  await page.goto("/patches");

  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page.getByText("Patch discarded")).toBeVisible();
});
