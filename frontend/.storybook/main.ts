import type { StorybookConfig } from "@storybook/nextjs-vite";

/**
 * Storybook configuration for the AutoDev Architect design system.
 *
 * Stories live next to their components under `components/ui/`. The a11y
 * addon runs axe-core checks against every story; see `preview.tsx` for the
 * enforcement level.
 */
const config: StorybookConfig = {
  stories: ["../components/**/*.stories.@(ts|tsx)"],
  addons: ["@storybook/addon-a11y"],
  framework: {
    name: "@storybook/nextjs-vite",
    options: {},
  },
};

export default config;
