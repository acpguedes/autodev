import { expect, test } from "playwright/test";

// E17-S2 DoD: e2e coverage for the Plans screen's approval-gate workflow.
//
// The screen talks exclusively to the `/v2/plans` control-plane endpoints
// (`frontend/lib/plans_v2.ts`), which resolve to `http://localhost:8000` in
// this dev-server setup (`lib/api_ext.ts::resolveBaseUrl`). We intercept
// every `**/v2/plans/**` request with `page.route()` and serve an in-memory
// fixture plan, mirroring the mocking style used for shell routes in
// `frontend/e2e/shell-navigation.spec.ts` (no real backend required).

type PlanStepState = "draft" | "under_review" | "approved" | "rejected" | "executing" | "completed";

interface PlanStepV2 {
  schemaVersion: string;
  session_id: string;
  step_index: number;
  content: string;
  state: PlanStepState;
  updated_at: string;
}

interface PlanV2 {
  schemaVersion: string;
  session_id: string;
  status: string;
  steps: PlanStepV2[];
}

const SESSION_ID = "session-e2e-plans";

/** Builds a fresh two-step fixture plan (one under review, one already approved). */
function makeInitialPlan(): PlanV2 {
  return {
    schemaVersion: "1",
    session_id: SESSION_ID,
    status: "under_review",
    steps: [
      {
        schemaVersion: "1",
        session_id: SESSION_ID,
        step_index: 0,
        content: "Draft the migration\n\nWrite the SQL migration for the new column.",
        state: "under_review",
        updated_at: "2026-01-01T00:00:00Z",
      },
      {
        schemaVersion: "1",
        session_id: SESSION_ID,
        step_index: 1,
        content: "Backfill existing rows",
        state: "approved",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ],
  };
}

/**
 * Registers a `page.route()` handler that serves an in-memory plan for
 * every `/v2/plans/{SESSION_ID}` request, mutating state so that sequential
 * actions in a single test (edit, approve, reject, add, remove, execute)
 * observe each other's effects, the same way the real API would.
 */
async function mockPlanApi(page: import("playwright/test").Page): Promise<{ plan: PlanV2 }> {
  const state = { plan: makeInitialPlan() };
  let nextStepIndex = state.plan.steps.length;

  await page.route("**/v2/plans/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const match = url.pathname.match(/\/v2\/plans\/([^/]+)(?:\/steps\/(\d+)(\/(approve|reject))?)?(\/steps)?(\/execute-approved)?$/);

    if (!match) {
      await route.fulfill({ status: 404, body: "not found" });
      return;
    }

    const stepIndex = match[2] !== undefined ? Number(match[2]) : null;
    const isApprove = match[4] === "approve";
    const isReject = match[4] === "reject";
    const isAddStep = match[5] === "/steps" && stepIndex === null;
    const isExecuteApproved = Boolean(match[6]);

    const findStep = (index: number): PlanStepV2 | undefined =>
      state.plan.steps.find((step) => step.step_index === index);

    // GET /v2/plans/{sessionId}
    if (method === "GET" && stepIndex === null && !isAddStep) {
      await route.fulfill({ json: state.plan });
      return;
    }

    // PUT /v2/plans/{sessionId}/steps/{stepIndex}
    if (method === "PUT" && stepIndex !== null) {
      const body = request.postDataJSON() as { content: string };
      const step = findStep(stepIndex);
      if (!step) {
        await route.fulfill({ status: 404, body: "step not found" });
        return;
      }
      step.content = body.content;
      await route.fulfill({ json: step });
      return;
    }

    // POST /v2/plans/{sessionId}/steps/{stepIndex}/approve
    if (method === "POST" && stepIndex !== null && isApprove) {
      const step = findStep(stepIndex);
      if (!step) {
        await route.fulfill({ status: 404, body: "step not found" });
        return;
      }
      step.state = "approved";
      await route.fulfill({ json: step });
      return;
    }

    // POST /v2/plans/{sessionId}/steps/{stepIndex}/reject
    if (method === "POST" && stepIndex !== null && isReject) {
      const step = findStep(stepIndex);
      if (!step) {
        await route.fulfill({ status: 404, body: "step not found" });
        return;
      }
      step.state = "rejected";
      await route.fulfill({ json: step });
      return;
    }

    // DELETE /v2/plans/{sessionId}/steps/{stepIndex}
    if (method === "DELETE" && stepIndex !== null) {
      state.plan.steps = state.plan.steps.filter((step) => step.step_index !== stepIndex);
      await route.fulfill({ json: state.plan });
      return;
    }

    // POST /v2/plans/{sessionId}/steps  (add step)
    if (method === "POST" && isAddStep) {
      const body = request.postDataJSON() as { content: string };
      const newStep: PlanStepV2 = {
        schemaVersion: "1",
        session_id: SESSION_ID,
        step_index: nextStepIndex,
        content: body.content,
        state: "draft",
        updated_at: "2026-01-01T00:00:00Z",
      };
      nextStepIndex += 1;
      state.plan.steps.push(newStep);
      await route.fulfill({ json: state.plan });
      return;
    }

    // POST /v2/plans/{sessionId}/execute-approved
    if (method === "POST" && isExecuteApproved) {
      state.plan.steps = state.plan.steps.map((step) =>
        step.state === "approved" ? { ...step, state: "completed" } : step,
      );
      state.plan.status = "completed";
      await route.fulfill({ json: state.plan });
      return;
    }

    await route.fulfill({ status: 404, body: "unhandled route" });
  });

  return state;
}

/** Loads the fixture plan via the session-id lookup form. */
async function loadFixturePlan(page: import("playwright/test").Page): Promise<void> {
  await page.goto("/plans");
  await page.getByLabel("Session").fill(SESSION_ID);
  await page.getByRole("button", { name: "Load" }).click();
  await expect(page.getByText("Draft the migration")).toBeVisible();
}

/**
 * Locates a stat card's value paragraph by its exact label text.
 *
 * Scoped to `<p>` elements only, since plain substring/text matching on
 * "Approved" or "Draft" would otherwise also match the step status
 * `Badge` (a `<div>`) and, for "Approved", the "Execute approved plan"
 * button's accessible name (Playwright role-name matching is substring
 * based by default).
 */
function statCardValue(page: import("playwright/test").Page, label: string) {
  return page
    .locator("p", { hasText: new RegExp(`^${label}$`) })
    .locator("xpath=following-sibling::p[1]");
}

test("loads a plan and renders its stats and steps", async ({ page }) => {
  await mockPlanApi(page);
  await loadFixturePlan(page);

  await expect(page.locator("p", { hasText: /^Steps$/ })).toBeVisible();
  await expect(page.locator("p", { hasText: /^Approved$/ })).toBeVisible();
  await expect(page.locator("p", { hasText: /^Pending review$/ })).toBeVisible();

  await expect(page.getByText("Backfill existing rows")).toBeVisible();
  await expect(page.getByText("Awaiting review")).toBeVisible();
});

test("edits a step's content and saves it", async ({ page }) => {
  await mockPlanApi(page);
  await loadFixturePlan(page);

  await page.getByRole("button", { name: "Edit" }).first().click();

  const titleInput = page.getByPlaceholder("Step title");
  await titleInput.fill("Draft the migration (updated)");
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByText("Draft the migration (updated)")).toBeVisible();
});

test("approves a step under review", async ({ page }) => {
  await mockPlanApi(page);
  await loadFixturePlan(page);

  await page.getByRole("button", { name: "Approve", exact: true }).click();

  await expect(statCardValue(page, "Pending review")).toHaveText("0");
  await expect(statCardValue(page, "Approved")).toHaveText("2");
});

test("rejects a step under review", async ({ page }) => {
  await mockPlanApi(page);
  await loadFixturePlan(page);

  await page.getByRole("button", { name: "Reject", exact: true }).click();

  await expect(page.getByText("Rejected")).toBeVisible();
});

test("adds a new step to the plan", async ({ page }) => {
  await mockPlanApi(page);
  await loadFixturePlan(page);

  await page.getByRole("button", { name: "+ Add step" }).click();

  await expect(page.getByText("New step")).toBeVisible();
  await expect(page.getByText("Draft", { exact: true })).toBeVisible();
  await expect(statCardValue(page, "Steps")).toHaveText("3");
});

test("approves a newly added draft step without reloading", async ({ page }) => {
  await mockPlanApi(page);
  await loadFixturePlan(page);

  await page.getByRole("button", { name: "+ Add step" }).click();
  await expect(page.getByText("Draft", { exact: true })).toBeVisible();

  // The new draft step's card is last in the list; its Approve button must be
  // offered immediately (the backend auto-promotes draft -> under_review when
  // the decision is applied, so the UI must not dead-end on fresh drafts).
  await page.getByRole("button", { name: "Approve", exact: true }).last().click();

  await expect(page.getByText("Draft", { exact: true })).toHaveCount(0);
  await expect(statCardValue(page, "Approved")).toHaveText("2");
});

test("removes a removable step", async ({ page }) => {
  await mockPlanApi(page);
  await loadFixturePlan(page);

  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(page.getByText("Rejected")).toBeVisible();

  await page.getByRole("button", { name: "Remove step 1" }).click();

  await expect(page.getByText("Draft the migration")).toHaveCount(0);
  await expect(page.getByText("Backfill existing rows")).toBeVisible();
});

test("executes approved steps from the sticky footer", async ({ page }) => {
  await mockPlanApi(page);
  await loadFixturePlan(page);

  const footerButton = page.getByRole("button", { name: "Execute approved plan" });
  await expect(footerButton).toBeEnabled();

  await footerButton.click();

  await expect(page.getByRole("button", { name: "Executing..." })).toHaveCount(0);
  await expect(page.getByText("Completed")).toBeVisible();
});
