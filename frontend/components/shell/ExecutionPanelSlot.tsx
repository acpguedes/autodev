"use client";

import { X } from "lucide-react";
import * as React from "react";
import useSWR from "swr";

import { TerminalPanel } from "@/components/terminal/TerminalPanel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslations } from "@/lib/i18n";

import { getTerminalStatus } from "@/lib/terminal_socket";

import type { PanelTab } from "./shellStore";
import { useShell } from "./ShellProvider";

/**
 * The dismissible right execution panel (prototype's 400px panel). Width and
 * open state come from the shell store, so the panel persists across client
 * navigation within a session. It is a `complementary` landmark (`aside` with
 * an accessible name), closes on Escape while open, and renders the current
 * page's execution content or a neutral empty state.
 *
 * @returns The execution panel when open, otherwise `null`.
 */
export function ExecutionPanelSlot(): React.JSX.Element | null {
  const { t } = useTranslations();
  const { panelOpen, panelWidth, setPanelOpen, panelContent, panelTab, setPanelTab } = useShell();
  // The Terminal tab exists only when the server reports the feature enabled;
  // any failure keeps the panel exactly as it was (fail closed).
  const terminalStatus = useSWR(panelOpen ? "terminal:status" : null, getTerminalStatus, {
    shouldRetryOnError: false,
  });
  const terminalEnabled = terminalStatus.data?.enabled === true;
  const activeTab: PanelTab = terminalEnabled ? panelTab : "activity";
  // Mount the terminal on first visit and keep it mounted across tab switches.
  const [terminalMounted, setTerminalMounted] = React.useState(false);
  React.useEffect(() => {
    if (terminalEnabled && activeTab === "terminal") {
      setTerminalMounted(true);
    }
  }, [terminalEnabled, activeTab]);

  React.useEffect(() => {
    if (!panelOpen) {
      return;
    }
    function onKeyDown(event: KeyboardEvent): void {
      // Escape belongs to the shell (vim, readline) while the terminal has focus.
      if (event.target instanceof Element && event.target.closest(".xterm")) {
        return;
      }
      if (event.key === "Escape") {
        setPanelOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [panelOpen, setPanelOpen]);

  if (!panelOpen) {
    return null;
  }

  const activityBody = (
    <>
      {panelContent ?? (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <span
              aria-hidden="true"
              className="mb-3.5 flex h-11 w-11 items-center justify-center rounded-ds-lg border border-ds-line text-ds-fg-3"
            >
              {"◇"}
            </span>
            <p className="max-w-[220px] text-[13px] leading-relaxed text-ds-fg-2">
              {t("shell.panel.emptyState")}
            </p>
          </div>
        )}
    </>
  );

  return (
    <aside
      aria-label={t("shell.panel.label")}
      style={{ width: panelWidth }}
      className="flex h-full shrink-0 flex-col border-l border-ds-line bg-ds-bg-2"
    >
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-ds-line px-4">
        <div className="flex items-center gap-2">
          <span aria-hidden="true" className="h-[9px] w-[9px] rounded-full bg-ds-fg-3" />
          <h2 className="text-[13px] font-semibold text-ds-fg">{t("shell.panel.title")}</h2>
        </div>
        <button
          type="button"
          onClick={() => setPanelOpen(false)}
          aria-label={t("shell.panel.close")}
          className="rounded-ds-sm p-1 text-ds-fg-3 transition-colors hover:text-ds-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent"
        >
          <X className="h-[18px] w-[18px]" aria-hidden="true" />
        </button>
      </div>

      {terminalEnabled ? (
        <Tabs
          value={activeTab}
          onValueChange={(value) => setPanelTab(value === "terminal" ? "terminal" : "activity")}
          className="flex min-h-0 flex-1 flex-col"
        >
          <TabsList
            aria-label={t("terminal.tabsLabel")}
            className="h-9 w-full shrink-0 justify-start gap-1 rounded-none border-b border-ds-line bg-transparent px-3 py-0"
          >
            <TabsTrigger
              value="activity"
              className="text-[13px] text-ds-fg-3 data-[state=active]:bg-ds-bg-3 data-[state=active]:text-ds-fg"
            >
              {t("terminal.tabActivity")}
            </TabsTrigger>
            <TabsTrigger
              value="terminal"
              className="text-[13px] text-ds-fg-3 data-[state=active]:bg-ds-bg-3 data-[state=active]:text-ds-fg"
            >
              {t("terminal.tabTerminal")}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="activity" className="mt-0 min-h-0 flex-1 overflow-auto">
            {activityBody}
          </TabsContent>
          <TabsContent
            value="terminal"
            forceMount={terminalMounted ? true : undefined}
            className="mt-0 min-h-0 flex-1 data-[state=inactive]:hidden"
          >
            {terminalMounted ? <TerminalPanel active={activeTab === "terminal"} /> : null}
          </TabsContent>
        </Tabs>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto">{activityBody}</div>
      )}
    </aside>
  );
}

export default ExecutionPanelSlot;
