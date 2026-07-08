import { defineConfig, devices } from "playwright/test";

// End-to-end tests for the Execution Control Center shell (E15-S2 DoD).
// Runs against the Next.js dev server; Playwright starts it when it is not
// already listening on :3000. Kept separate from Vitest: the `unit` and
// `storybook` projects in vitest.config.ts only match *.test.ts and
// *.stories.tsx, while e2e specs live in e2e/**/*.spec.ts.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
