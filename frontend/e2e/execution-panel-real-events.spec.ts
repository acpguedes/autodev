import { expect, test } from "playwright/test";

// E64: the chat's execution panel is a live record of real operations. It must
// show a real command and its stdout from the run's SSE stream, and must not
// show the assistant's message text (which the chat itself carries).

const API_ORIGIN = "http://localhost:8000";
const SESSION_ID = "session-e64";
const TURN_ID = "turn-e64";
const ASSISTANT_TEXT = "I will now run the tests for you.";

test("panel shows a real command with stdout and not the assistant's text", async ({ page }) => {
  await page.route(`${API_ORIGIN}/config`, (route) =>
    route.fulfill({
      json: {
        config: {
          repository: { repository_label: "autodev", project_root: "/repo", default_goal: "Improve" },
        },
      },
    })
  );
  await page.route(`${API_ORIGIN}/sessions`, (route) =>
    route.fulfill({
      json: [
        {
          session_id: SESSION_ID,
          goal: "Run tests",
          plan: ["step"],
          status: "running",
          history: [{ role: "assistant", content: ASSISTANT_TEXT }],
        },
      ],
    })
  );
  // A zero-action planner result: must not leak its text into the panel.
  await page.route(`${API_ORIGIN}/sessions/*/runs`, (route) =>
    route.fulfill({
      json: [
        {
          run_id: TURN_ID,
          run_type: "agent",
          status: "completed",
          results: [
            { agent: "planner", content: ASSISTANT_TEXT, metadata: { description: ASSISTANT_TEXT, actions: [] } },
          ],
        },
      ],
    })
  );
  await page.route(`${API_ORIGIN}/sessions/*/execution-plan`, (route) =>
    route.fulfill({ json: { session_id: SESSION_ID, status: "ready", tasks: [] } })
  );
  await page.route(`${API_ORIGIN}/v2/sessions/*/turns*`, (route) =>
    route.fulfill({
      json: {
        schemaVersion: "1",
        items: [
          {
            schemaVersion: "1",
            turnId: TURN_ID,
            sessionId: SESSION_ID,
            message: "run the tests",
            status: "completed",
            runType: "agent",
            currentState: "completed",
            createdAt: "2026-01-01T00:00:00Z",
            history: [],
            results: [],
            steps: [],
          },
        ],
        page: { limit: 50, offset: 0, total: 1 },
      },
    })
  );
  await page.route(`${API_ORIGIN}/v2/provider-config/status`, (route) =>
    route.fulfill({
      json: { schemaVersion: "1", configured: true, healthy: true, name: "stub", model: "stub-1" },
    })
  );
  await page.route(`**/v2/runs/${TURN_ID}/events/stream**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: [
        'id: 1\nevent: execution.action.started\ndata: {"actionId":"a1","taskId":"t1","type":"run_command","command":["pytest","-q"],"sourceAgent":"coder"}\n\n',
        'id: 2\nevent: execution.action.completed\ndata: {"actionId":"a1","taskId":"t1","status":"succeeded","exitCode":0,"stdout":"3 passed in 0.12s"}\n\n',
      ].join(""),
    })
  );

  await page.goto("/");

  const panel = page.getByRole("complementary", { name: /execution|panel/i });
  await expect(panel.getByText("$ pytest -q")).toBeVisible();
  await expect(panel.getByText("3 passed in 0.12s")).toBeVisible();
  await expect(panel.getByText(/exit code: 0/)).toBeVisible();
  await expect(panel.getByText(ASSISTANT_TEXT)).toHaveCount(0);
});
