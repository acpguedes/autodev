import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import * as React from "react";

import { ThemeProvider } from "@/components/ThemeProvider";
import { I18nProvider } from "@/lib/i18n";

import { AppShell } from "./AppShell";
import { ShellProvider, useExecutionPanel, useShellHeader } from "./ShellProvider";
import { shellStore } from "./shellStore";

// Storybook documentation + automated a11y (axe) coverage for the
// Execution Control Center shell (E15-S2 DoD: "shell usage documented"
// and "a11y audit of the three regions"). These stories run headlessly
// through the `storybook` Vitest project, which enforces the a11y addon.

/** Sample routed page that publishes header content, like real pages do. */
function DemoPage(): React.JSX.Element {
  useShellHeader({
    title: "Plans",
    subtitle: "Plan generation and review",
  });

  return (
    <div className="p-7">
      <p className="max-w-prose text-[13.5px] leading-relaxed text-ds-fg-2">
        Routed page content renders here, inside the skip-link target. Pages
        publish their contextual header via <code>useShellHeader</code> and may
        stream execution output into the right panel via{" "}
        <code>useExecutionPanel</code>.
      </p>
    </div>
  );
}

/** DemoPage variant that also opens and fills the execution panel. */
function DemoPageWithPanel(): React.JSX.Element {
  useShellHeader({ title: "Chat", subtitle: "Active session" });
  const panel = React.useMemo(
    () => (
      <div className="p-4 font-mono text-[12px] leading-relaxed text-ds-fg-2">
        planning → analysis → patch → validation
      </div>
    ),
    []
  );
  useExecutionPanel(panel);

  React.useEffect(() => {
    shellStore.setPanelOpen(true);
    return () => shellStore.setPanelOpen(false);
  }, []);

  return (
    <div className="p-7 text-[13.5px] text-ds-fg-2">
      Page content with the execution panel open alongside.
    </div>
  );
}

const meta: Meta<typeof AppShell> = {
  title: "Shell/AppShell",
  component: AppShell,
  // `ShellProvider` calls `next/navigation`'s `useRouter`, which needs the App
  // Router mock (`AppRouterContext`), not Storybook's default Pages Router
  // mock — without this the story throws "invariant expected app router to
  // be mounted".
  parameters: { layout: "fullscreen", nextjs: { appDirectory: true } },
  decorators: [
    (Story) => (
      <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
        <I18nProvider>
          <ShellProvider>
            <Story />
          </ShellProvider>
        </I18nProvider>
      </ThemeProvider>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof AppShell>;

/**
 * The full three-region shell: 250px sidebar rail (brand, workspace switcher,
 * Workspace + Legacy nav, provider card, theme toggle), 64px contextual
 * header (page title, repo chip, Execution toggle, "+ New session"), and the
 * routed content region. The execution panel is closed by default.
 */
export const Default: Story = {
  render: () => (
    <AppShell>
      <DemoPage />
    </AppShell>
  ),
};

/**
 * The shell with the dismissible 400px execution panel open and a page
 * publishing content into it. The panel is a `complementary` landmark and
 * closes on Escape or its labelled close button.
 */
export const ExecutionPanelOpen: Story = {
  render: () => (
    <AppShell>
      <DemoPageWithPanel />
    </AppShell>
  ),
};
