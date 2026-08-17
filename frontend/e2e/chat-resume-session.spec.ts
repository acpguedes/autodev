import { expect, test } from "playwright/test";

// E17 S1<->S4 integration gap: `/sessions` emits a reopen-as-chat link
// (`/?sessionId=<id>`, see `components/sessions/SessionRow.tsx`) that the chat
// screen never consumed, so the link always landed on the most recent session
// instead of the requested one.
//
// Like the other E17 specs, these tests intercept the browser's API calls with
// deterministic fixtures rather than depending on a seeded live backend, so
// they assert real rendered state driven by the actual page components.

const API_ORIGIN = "http://localhost:8000";

type SessionFixture = {
  session_id: string;
  goal: string;
  history: { role: string; content: string }[];
};

const LATEST: SessionFixture = {
  session_id: "session-latest",
  goal: "Latest session goal",
  history: [{ role: "assistant", content: "Latest session transcript" }],
};

const OLDER: SessionFixture = {
  session_id: "session-older",
  goal: "Older session goal",
  history: [{ role: "assistant", content: "Older session transcript" }],
};

/**
 * Serve the endpoints the chat screen bootstraps from. `listSessions` returns
 * the sessions newest-first, mirroring the backend ordering the screen relies
 * on when no session is explicitly requested.
 */
async function stubChatWorkspace(
  page: import("playwright/test").Page,
  sessions: SessionFixture[]
): Promise<void> {
  await page.route(`${API_ORIGIN}/config`, async (route) => {
    await route.fulfill({
      json: {
        config: {
          repository: {
            repository_label: "autodev",
            project_root: "/repo",
            default_goal: "Improve the platform",
          },
        },
      },
    });
  });

  await page.route(`${API_ORIGIN}/sessions`, async (route) => {
    await route.fulfill({
      json: sessions.map((session) => ({
        session_id: session.session_id,
        goal: session.goal,
        plan: [`Plan step for ${session.session_id}`],
        status: "running",
        history: session.history,
      })),
    });
  });

  await page.route(`${API_ORIGIN}/sessions/*/runs`, async (route) => {
    await route.fulfill({ json: [] });
  });

  await page.route(`${API_ORIGIN}/sessions/*/execution-plan`, async (route) => {
    await route.fulfill({ json: { session_id: "stub", status: "ready", tasks: [] } });
  });

  await page.route(`${API_ORIGIN}/v2/sessions/*/turns*`, async (route) => {
    await route.fulfill({
      json: { schemaVersion: "1", items: [], page: { limit: 50, offset: 0, total: 0 } },
    });
  });

  await page.route(`${API_ORIGIN}/v2/provider-config/status`, async (route) => {
    await route.fulfill({
      json: { schemaVersion: "1", configured: true, healthy: true, name: "stub", model: "stub-1" },
    });
  });
}

/**
 * The chat screen's error banner. Scoped to non-empty alerts because Next.js
 * always renders an empty `role="alert"` route announcer, which a bare
 * `getByRole("alert")` would match.
 */
function chatNotice(page: import("playwright/test").Page) {
  return page.getByRole("alert").filter({ hasText: /\S/ });
}

test.describe("Chat reopen-as-chat deep link", () => {
  test("resumes the session named by ?sessionId= instead of the latest one", async ({ page }) => {
    await stubChatWorkspace(page, [LATEST, OLDER]);

    await page.goto(`/?sessionId=${OLDER.session_id}`);

    // The session meta line renders the adopted session id.
    await expect(page.getByText(`Session: ${OLDER.session_id}`)).toBeVisible();
    // ...and the transcript is the requested session's, not the latest one's.
    await expect(page.getByText("Older session transcript")).toBeVisible();
    await expect(page.getByText("Latest session transcript")).toHaveCount(0);
  });

  test("falls back to the most recent session with a notice when the id is stale", async ({
    page,
  }) => {
    await stubChatWorkspace(page, [LATEST, OLDER]);

    await page.goto("/?sessionId=session-deleted");

    await expect(chatNotice(page)).toContainText("session-deleted");
    await expect(page.getByText(`Session: ${LATEST.session_id}`)).toBeVisible();
    await expect(page.getByText("Latest session transcript")).toBeVisible();
  });

  test("keeps the latest session when no sessionId is requested", async ({ page }) => {
    await stubChatWorkspace(page, [LATEST, OLDER]);

    await page.goto("/");

    await expect(page.getByText(`Session: ${LATEST.session_id}`)).toBeVisible();
    await expect(chatNotice(page)).toHaveCount(0);
  });
});
