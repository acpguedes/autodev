import type { Preview } from "@storybook/nextjs-vite";
import React from "react";

import "../styles/globals.css";

/**
 * Applies the selected theme class to the document root so that portaled
 * content (Radix dialog/select/toast render into document.body) resolves the
 * same design tokens as in the app, where next-themes sets the class on html.
 */
function ThemeApplier({
  theme,
  children,
}: {
  theme: string;
  children: React.ReactNode;
}) {
  React.useEffect(() => {
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(theme);
    document.body.style.background = "hsl(var(--background))";
    document.body.style.color = "hsl(var(--foreground))";
  }, [theme]);
  return (
    <div
      style={{
        minHeight: "100vh",
        padding: "1.5rem",
        fontFamily: "Inter, system-ui, sans-serif",
      }}
    >
      {children}
    </div>
  );
}

/**
 * Global Storybook preview configuration.
 *
 * Wires the design-token light/dark themes into a toolbar control and
 * enforces WCAG 2.2 AA accessibility by failing the story test when the
 * a11y addon (axe-core) reports a violation.
 */
const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    a11y: {
      test: "error",
    },
    layout: "padded",
  },
  globalTypes: {
    theme: {
      description: "Design token theme",
      toolbar: {
        title: "Theme",
        icon: "circlehollow",
        items: [
          { value: "dark", title: "Dark" },
          { value: "light", title: "Light" },
        ],
        dynamicTitle: true,
      },
    },
  },
  initialGlobals: { theme: "dark" },
  decorators: [
    (Story, context) => {
      const theme = (context.globals.theme as string) || "dark";
      return (
        <ThemeApplier theme={theme}>
          <Story />
        </ThemeApplier>
      );
    },
  ],
};

export default preview;
