import path from "node:path";
import { fileURLToPath } from "node:url";

import { storybookTest } from "@storybook/addon-vitest/vitest-plugin";
import { playwright } from "@vitest/browser-playwright";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const dirname =
  typeof __dirname !== "undefined"
    ? __dirname
    : path.dirname(fileURLToPath(import.meta.url));

// Two projects: plain unit tests (Node) and Storybook stories run as
// browser tests via the Storybook Vitest addon, which also enforces the
// a11y addon's axe-core checks. See:
// https://storybook.js.org/docs/writing-tests/integrations/vitest-addon
export default defineConfig({
  test: {
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          environment: "node",
          include: ["lib/**/*.test.ts", "components/**/*.test.ts"],
        },
      },
      {
        extends: true,
        plugins: [react()],
        esbuild: false,
        oxc: { jsx: { runtime: "automatic" } },
        resolve: { alias: { "@": dirname } },
        test: {
          // Separate project (not just an extra `include` glob on "unit"):
          // component tests render real DOM via @testing-library/react and
          // need `environment: "jsdom"` plus a real JSX transform (the
          // repo's tsconfig.json sets `"jsx": "preserve"` for Next.js's own
          // SWC compiler, which Vite's default esbuild transform can't
          // parse — @vitejs/plugin-react provides an independent one), none
          // of which plain `lib/**/*.test.ts` Node-environment tests need.
          name: "component",
          environment: "jsdom",
          include: ["components/**/*.test.tsx"],
        },
      },
      {
        extends: true,
        plugins: [
          storybookTest({ configDir: path.join(dirname, ".storybook") }),
        ],
        test: {
          name: "storybook",
          browser: {
            enabled: true,
            headless: true,
            provider: playwright(),
            instances: [{ browser: "chromium" }],
          },
        },
      },
    ],
  },
});
