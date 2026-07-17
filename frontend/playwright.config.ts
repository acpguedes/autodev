import { defineConfig, devices } from "playwright/test";

// End-to-end tests for the Execution Control Center shell (E15-S2 DoD).
// Runs against the Next.js dev server; Playwright starts it when it is not
// already listening on the target port. Kept separate from Vitest: the
// `unit` and `storybook` projects in vitest.config.ts only match *.test.ts
// and *.stories.tsx, while e2e specs live in e2e/**/*.spec.ts.
//
// The port defaults to 3000 but can be overridden with PLAYWRIGHT_PORT —
// useful when multiple git worktrees each run their own `npm run dev` on
// the same host and would otherwise collide on the default port (in which
// case `reuseExistingServer` would silently attach to a sibling worktree's
// server instead of this one).
const PORT = process.env.PLAYWRIGHT_PORT ?? "3000";
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // Two parallel workers thrash the single cold Next.js dev server on the
  // 4-core CI runner (route compiles queue behind each other and tests hit
  // the 30s cap). Serialize on CI; keep parallelism for local runs.
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  // CI runners cold-compile each Next.js dev-server route on first visit;
  // the 5s default assertion timeout is too tight for that first paint,
  // and the 30s default test timeout is too tight for compile + retries.
  timeout: process.env.CI ? 60_000 : 30_000,
  expect: { timeout: process.env.CI ? 15_000 : 5_000 },
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npm run dev -- -p ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
