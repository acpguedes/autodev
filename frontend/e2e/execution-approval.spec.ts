import { expect, test } from "playwright/test";

// E14-S5 DoD: e2e coverage for the Execution screen's approval workflow —
// approve a pending decision, see it clear from the list, watch a run's
// real-time execution log.
//
// The screen talks exclusively to the `/v2/execution/*` control-plane
// endpoints (`frontend/lib/execution_v2.ts`) plus the E9-S2 SSE run-events
// stream for the log. We intercept every request with `page.route()` and
// serve in-memory fixtures, mirroring `plans-approval-gates.spec.ts` (no
// real backend required).

interface PendingDecisionV2 {
  decisionId: string;
  runId: string;
  taskId: string;
  category: string;
  prompt: string;
  status: string;
  createdAt: string;
  expiresAt: string;
}

const RUN_ID = "run-e2e-execution";

function makeInitialDecisions(): PendingDecisionV2[] {
  return [
    {
      decisionId: "dec-1",
      runId: RUN_ID,
      taskId: "coding-1",
      category: "fs-write",
      prompt: "Approve create_file for task 'Implement backend/api'?",
      status: "pending",
      createdAt: "2026-01-01T00:00:00Z",
      expiresAt: "2026-01-01T01:00:00Z",
    },
  ];
}

/**
 * Registers `page.route()` handlers serving in-memory fixtures for the
 * decisions/permissions/resolve/revoke endpoints, mutating state so a
 * resolved decision disappears from a subsequent list call.
 */
async function mockExecutionApi(page: import("playwright/test").Page): Promise<void> {
  const state = { decisions: makeInitialDecisions(), permissions: [] as unknown[] };

  await page.route("**/v2/execution/decisions", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: { schemaVersion: "2.0", decisions: state.decisions } });
      return;
    }
    await route.fulfill({ status: 404, body: "unhandled route" });
  });

  await page.route("**/v2/execution/decisions/*/resolve", async (route) => {
    const url = new URL(route.request().url());
    const decisionId = url.pathname.split("/").at(-2);
    const decision = state.decisions.find((entry) => entry.decisionId === decisionId);
    if (!decision) {
      await route.fulfill({ status: 404, body: "not found" });
      return;
    }
    const body = route.request().postDataJSON() as { decision: string };
    decision.status = body.decision === "approve" ? "approved" : "denied";
    state.decisions = state.decisions.filter((entry) => entry.decisionId !== decisionId);
    await route.fulfill({ json: decision });
  });

  await page.route("**/v2/execution/policy/dynamic", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: { schemaVersion: "2.0", permissions: state.permissions } });
      return;
    }
    await route.fulfill({ status: 404, body: "unhandled route" });
  });

  await page.route(`**/v2/runs/${RUN_ID}/events/stream**`, async (route) => {
    const frames = [
      'event: execution.action.started\ndata: {"actionId":"a1","taskId":"coding-1","type":"create_file"}\n\n',
      'event: execution.action.completed\ndata: {"actionId":"a1","taskId":"coding-1","status":"succeeded","exitCode":0}\n\n',
    ].join("");
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: frames,
    });
  });
}

test("loads pending decisions and approves one", async ({ page }) => {
  await mockExecutionApi(page);
  await page.goto("/execution");

  await expect(page.getByText("Approve create_file for task 'Implement backend/api'?")).toBeVisible();

  await page.getByRole("button", { name: "Approve", exact: true }).click();

  await expect(page.getByText("Approve create_file for task 'Implement backend/api'?")).toHaveCount(0);
  await expect(page.getByText("No pending decisions for this tenant.")).toBeVisible();
});

test("watches a run's real-time execution log", async ({ page }) => {
  await mockExecutionApi(page);
  await page.goto("/execution");

  await page.getByLabel("Run").fill(RUN_ID);
  await page.getByRole("button", { name: "Watch" }).click();

  await expect(page.getByText(/execution\.action\.started.*coding-1.*a1/)).toBeVisible();
  await expect(page.getByText(/execution\.action\.completed.*coding-1.*a1.*succeeded.*exit 0/)).toBeVisible();
});
