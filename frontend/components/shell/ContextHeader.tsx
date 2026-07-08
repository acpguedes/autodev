"use client";

import { PanelRight, Plus } from "lucide-react";
import * as React from "react";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import { getRuntimeConfig } from "@/lib/api";

import { useShell } from "./ShellProvider";

/** Fixed contextual-header height in CSS pixels (prototype's 64px header). */
const HEADER_HEIGHT = 64;

/**
 * The 64px contextual header: per-view title/subtitle published via
 * {@link useShellHeader}, an active-repository chip, the execution-panel
 * toggle, and the "+ New session" primary action.
 *
 * @returns The contextual header.
 */
export function ContextHeader(): React.JSX.Element {
  const { header, panelOpen, togglePanel, triggerNewSession } = useShell();
  const config = useSWR("shell:runtime-config", getRuntimeConfig, {
    shouldRetryOnError: false,
  });
  const repositoryLabel = config.data?.config.repository.repository_label;

  return (
    <header
      style={{ height: HEADER_HEIGHT }}
      className="flex shrink-0 items-center justify-between gap-4 border-b border-ds-line bg-ds-bg px-7"
    >
      <div className="flex min-w-0 items-center gap-3.5">
        <div className="min-w-0 leading-tight">
          <h1 className="truncate font-serif text-[17px] font-semibold text-ds-fg">
            {header.title}
          </h1>
          {header.subtitle ? (
            <p className="truncate text-[12px] text-ds-fg-3">{header.subtitle}</p>
          ) : null}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2.5">
        {repositoryLabel ? (
          <span className="hidden items-center gap-2 rounded-ds-md border border-ds-line bg-ds-bg-2 px-2.5 py-1.5 text-[12px] text-ds-fg-2 sm:flex">
            <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-ds-fg-3" />
            <span className="max-w-[16rem] truncate">{repositoryLabel} · main</span>
          </span>
        ) : null}

        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-pressed={panelOpen}
          onClick={togglePanel}
          className="gap-1.5"
        >
          <PanelRight className="h-4 w-4" aria-hidden="true" />
          <span className="hidden sm:inline">Execution</span>
        </Button>

        <Button type="button" size="sm" onClick={triggerNewSession} className="gap-1.5">
          <Plus className="h-4 w-4" aria-hidden="true" />
          New session
        </Button>
      </div>
    </header>
  );
}

export default ContextHeader;
