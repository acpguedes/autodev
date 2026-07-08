"use client";

import { Badge } from "@/components/ui/badge";
import { useTranslations } from "@/lib/i18n";

import type { RunResponse } from "../lib/api";

type ExecutionConsolePanelProps = {
  runs: RunResponse[];
  isBusy: boolean;
};

type ConsoleEntry = {
  id: string;
  labelKey: "executionConsole.runTypePlanExecution" | "executionConsole.runTypeAgent";
  command: string;
  output: string;
  status: string;
};

function buildConsoleEntries(runs: RunResponse[]): ConsoleEntry[] {
  return runs.flatMap((run) =>
    run.results.map((result, index) => {
      const taskTitle =
        typeof result.metadata?.title === "string" ? result.metadata.title : result.content;
      const taskDescription =
        typeof result.metadata?.description === "string"
          ? result.metadata.description
          : result.content;
      const category =
        typeof result.metadata?.category === "string" ? result.metadata.category : result.agent;
      const sourceAgent =
        typeof result.metadata?.source_agent === "string"
          ? result.metadata.source_agent
          : result.agent;
      const status =
        typeof result.metadata?.status === "string" ? result.metadata.status : run.status;

      return {
        id: `${run.run_id}-${index}`,
        labelKey:
          run.run_type === "plan_execution"
            ? ("executionConsole.runTypePlanExecution" as const)
            : ("executionConsole.runTypeAgent" as const),
        command:
          run.run_type === "plan_execution"
            ? `${category}: ${taskTitle}`
            : `${sourceAgent} -> ${taskTitle}`,
        output: taskDescription,
        status,
      };
    })
  );
}

export function ExecutionConsolePanel({ runs, isBusy }: ExecutionConsolePanelProps) {
  const { t } = useTranslations();
  const entries = buildConsoleEntries(runs);

  return (
    // Rendered inside the shell's execution-panel `aside` (E15-S2), so this is
    // a plain container rather than a nested `complementary` landmark.
    <div className="flex h-full flex-col gap-4" aria-live="polite">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">
            {t("executionConsole.sectionLabel")}
          </p>
          <h2 className="font-serif text-lg font-semibold text-ds-fg">
            {t("executionConsole.title")}
          </h2>
        </div>
        <Badge
          variant="secondary"
          className={isBusy ? "bg-ds-accent/15 text-ds-accent-strong" : undefined}
        >
          {isBusy ? t("executionConsole.statusBusy") : t("executionConsole.statusReady")}
        </Badge>
      </div>

      <p className="text-sm text-ds-fg-3">
        {isBusy
          ? t("executionConsole.descriptionBusy")
          : t("executionConsole.descriptionIdle")}
      </p>

      {entries.length === 0 ? (
        <div className="rounded-ds-md border border-dashed border-ds-line bg-ds-bg-3 p-4">
          <p className="text-sm text-ds-fg-3">{t("executionConsole.emptyState")}</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3 overflow-y-auto">
          {entries.map((entry) => (
            <article
              className="flex flex-col gap-2 rounded-ds-md border border-ds-line bg-ds-bg-3 p-3"
              key={entry.id}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">
                  {t(entry.labelKey)}
                </span>
                <Badge variant="secondary">{entry.status}</Badge>
              </div>
              <code className="font-mono text-[13px] text-ds-fg-2">{entry.command}</code>
              <pre className="overflow-x-auto whitespace-pre-wrap rounded-ds-sm bg-ds-bg-4 p-3 font-mono text-xs text-ds-fg-2">
                {entry.output}
              </pre>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

export default ExecutionConsolePanel;
