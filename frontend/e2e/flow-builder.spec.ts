import { expect, test } from "playwright/test";

// E17-S6 DoD: e2e coverage for the "Execution Control Center" flow builder
// (palette + canvas + inspector realignment of the visual flow editor).
//
// The backend may be offline while these run (see shell-navigation.spec.ts);
// the editor loads a built-in sample manifest client-side and the palette's
// "Agents"/"Flow control" sections never depend on network data, so only
// the Flows-library listing and the Save action's server round-trip are
// network-dependent — those are asserted loosely (toast appears, whichever
// outcome) rather than pinned to a specific backend response.

test("renders the three-column flow builder: palette, canvas, inspector", async ({ page }) => {
  await page.goto("/flows");

  // Palette (left column): Flows library, Agents, Flow control sections.
  // Scoped to the palette landmark — some canvas node labels (e.g. the
  // sample flow's "quality-gate" conditional node) share a name prefix
  // with palette entries ("Conditional …"), so an unscoped query would be
  // ambiguous (strict-mode violation).
  const palette = page.getByRole("group", { name: "Flow palette" });
  await expect(palette.getByRole("heading", { name: "Flows library" })).toBeVisible();
  await expect(palette.getByRole("heading", { name: "Agents", exact: true })).toBeVisible();
  await expect(palette.getByRole("heading", { name: "Flow control" })).toBeVisible();
  await expect(palette.getByRole("button", { name: "New blank flow" })).toBeVisible();
  await expect(palette.getByRole("button", { name: /^Planner /i })).toBeVisible();
  await expect(palette.getByRole("button", { name: /^Conditional /i })).toBeVisible();

  // Canvas (center column): the sample flow's first node is rendered.
  const canvas = page.getByRole("group", { name: "Flow graph canvas" });
  await expect(canvas).toBeVisible();
  await expect(canvas.getByRole("button", { name: /^agent node plan/i })).toBeVisible();

  // Inspector (right column): tabs for Inspector / flow.yaml / Issues.
  await expect(page.getByRole("tab", { name: "Inspector" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "flow.yaml" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /^Issues/ })).toBeVisible();
});

test("inserting a Coder agent from the palette connects it to the selected node", async ({
  page,
}) => {
  await page.goto("/flows");

  const palette = page.getByRole("group", { name: "Flow palette" });
  const canvas = page.getByRole("group", { name: "Flow graph canvas" });
  const planNode = canvas.getByRole("button", { name: /^agent node plan/i });
  await planNode.click();
  await expect(planNode).toHaveAttribute("aria-pressed", "true");

  await palette.getByRole("button", { name: /^Coder /i }).click();

  // A new "coder" node is inserted and auto-selected...
  const coderNode = canvas.getByRole("button", { name: /^agent node coder/i });
  await expect(coderNode).toBeVisible();
  await expect(coderNode).toHaveAttribute("aria-pressed", "true");

  // ...connected by a new edge from the previously selected "plan" node.
  await expect(canvas.locator("p.sr-only")).toContainText("plan to coder");

  // The inspector switches to show the newly inserted node's fields.
  await expect(page.getByRole("tabpanel", { name: "Inspector" })).toContainText("coder");
});

test("Clear empties the canvas", async ({ page }) => {
  await page.goto("/flows");

  const canvas = page.getByRole("group", { name: "Flow graph canvas" });
  await expect(canvas.getByRole("button", { name: /node/i }).first()).toBeVisible();

  await page.getByRole("button", { name: "Clear" }).click();

  await expect(canvas.getByRole("button", { name: /node/i })).toHaveCount(0);
  await expect(canvas.locator("p.sr-only")).toHaveText("The flow has no edges.");
  await expect(page.getByRole("status")).toContainText("Canvas cleared");
});

test("Save validates the manifest and reports the outcome via toast", async ({ page }) => {
  await page.goto("/flows");

  await page.getByRole("button", { name: "Save" }).click();

  // Whether the /v2/flows/validate round-trip succeeds (export confirmed)
  // or fails (backend unavailable / server-side validation error), the
  // save action always surfaces its outcome as a toast — never a silent
  // failure. Scoped to the toaster stack (data-testid="toaster") since an
  // unscoped role=alert query also matches Next.js's (empty) built-in
  // route announcer, a strict-mode violation.
  const toaster = page.getByTestId("toaster");
  await expect(toaster).toContainText(
    /flow\.yaml exported|Could not validate flow\.yaml|Server validation failed/
  );
});
