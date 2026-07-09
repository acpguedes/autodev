"use client";

import * as React from "react";

import { useTranslations } from "@/lib/i18n";

import { ContextHeader } from "./ContextHeader";
import { ExecutionPanelSlot } from "./ExecutionPanelSlot";
import { SidebarRail } from "./SidebarRail";

/** DOM id of the main content region, targeted by the skip link. */
const MAIN_CONTENT_ID = "shell-main-content";

/**
 * Compose the three shell regions — sidebar rail, contextual header, and
 * dismissible execution panel — around the routed page content. A leading
 * skip link and explicit `aside`/`header`/`main`/`complementary` landmarks
 * keep the shell keyboard-navigable and WCAG 2.2 AA conformant.
 *
 * @param props - The routed page content.
 * @returns The full application shell.
 */
export function AppShell({ children }: { children: React.ReactNode }): React.JSX.Element {
  const { t } = useTranslations();
  return (
    <div className="flex h-screen w-full overflow-hidden bg-ds-bg font-sans text-ds-fg">
      <a
        href={`#${MAIN_CONTENT_ID}`}
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-ds-md focus:bg-ds-accent focus:px-3 focus:py-2 focus:text-ds-accent-fg"
      >
        {t("shell.skipToContent")}
      </a>

      <SidebarRail />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <ContextHeader />
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <main id={MAIN_CONTENT_ID} tabIndex={-1} className="min-w-0 flex-1 overflow-auto">
            {children}
          </main>
          <ExecutionPanelSlot />
        </div>
      </div>
    </div>
  );
}

export default AppShell;
