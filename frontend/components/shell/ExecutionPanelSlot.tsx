"use client";

import { X } from "lucide-react";
import * as React from "react";

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
  const { panelOpen, panelWidth, setPanelOpen, panelContent } = useShell();

  React.useEffect(() => {
    if (!panelOpen) {
      return;
    }
    function onKeyDown(event: KeyboardEvent): void {
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

  return (
    <aside
      aria-label="Execution panel"
      style={{ width: panelWidth }}
      className="flex h-full shrink-0 flex-col border-l border-ds-line bg-ds-bg-2"
    >
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-ds-line px-4">
        <div className="flex items-center gap-2">
          <span aria-hidden="true" className="h-[9px] w-[9px] rounded-full bg-ds-fg-3" />
          <h2 className="text-[13px] font-semibold text-ds-fg">Execution</h2>
        </div>
        <button
          type="button"
          onClick={() => setPanelOpen(false)}
          aria-label="Close execution panel"
          className="rounded-ds-sm p-1 text-ds-fg-3 transition-colors hover:text-ds-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent"
        >
          <X className="h-[18px] w-[18px]" aria-hidden="true" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {panelContent ?? (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <span
              aria-hidden="true"
              className="mb-3.5 flex h-11 w-11 items-center justify-center rounded-ds-lg border border-ds-line text-ds-fg-3"
            >
              ◇
            </span>
            <p className="max-w-[220px] text-[13px] leading-relaxed text-ds-fg-3">
              The planning, analysis, patch and validation timeline appears here in real time.
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}

export default ExecutionPanelSlot;
