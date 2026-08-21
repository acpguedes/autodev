"use client";

import { Badge } from "@/components/ui/badge";
import { useTranslations } from "@/lib/i18n";
import { transcriptLineFromActionResult } from "@/lib/transcript";

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

/** One raw `ExecutionResult.to_dict()` entry, as carried in `result.metadata.actions[]`. */
type ActionResultRecord = {
  action_id: string;
  status: string;
  command?: string[] | null;
  path?: string | null;
  stdout?: string;
  stderr?: string;
  error?: string | null;
  diff?: string;
};

function actionRecords(value: unknown): ActionResultRecord[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (entry): entry is ActionResultRecord =>
      typeof entry === "object" && entry !== null && typeof (entry as { action_id?: unknown }).action_id === "string"
  );
}

/**
 * Build one transcript entry per real action (E43-S2) -- a genuine
 * `$ pytest -q` / `$ write main.py` command line with that action's real
 * stdout/stderr/error, not the task's static pre-execution description
 * echoed back as if it were the output.
 *
 * Falls back to the task title/description only for a task that has not
 * dispatched any actions yet (e.g. planning/analysis steps E43 doesn't
 * derive actions for).
 */
function buildConsoleEntries(runs: RunResponse[]): ConsoleEntry[] {
  return runs.flatMap((run) =>
    run.results.flatMap((result, index) => {
      const taskTitle =
        typeof result.metadata?.title === "string" ? result.metadata.title : result.content;
      const category =
        typeof result.metadata?.category === "string" ? result.metadata.category : result.agent;
      const sourceAgent =
        typeof result.metadata?.source_agent === "string"
          ? result.metadata.source_agent
          : result.agent;
      const taskStatus =
        typeof result.metadata?.status === "string" ? result.metadata.status : run.status;
      const labelKey =
        run.run_type === "plan_execution"
          ? ("executionConsole.runTypePlanExecution" as const)
          : ("executionConsole.runTypeAgent" as const);

      const actions = actionRecords(result.metadata?.actions);
      if (actions.length === 0) {
        const taskDescription =
          typeof result.metadata?.description === "string"
            ? result.metadata.description
            : result.content;
        return [
          {
            id: `${run.run_id}-${index}`,
            labelKey,
            command:
              run.run_type === "plan_execution"
                ? `${category}: ${taskTitle}`
                : `${sourceAgent} -> ${taskTitle}`,
            output: taskDescription,
            status: taskStatus,
          },
        ];
      }

      return actions.map((action) => {
        const line = transcriptLineFromActionResult(action);
        return {
          id: `${run.run_id}-${index}-${action.action_id}`,
          labelKey,
          command: line.command,
          output: line.output,
          status: action.status,
        };
      });
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
