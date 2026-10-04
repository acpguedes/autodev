"use client";

import { Badge } from "@/components/ui/badge";
import { useTranslations } from "@/lib/i18n";
import { useExecutionActionLog, type ExecutionActionEvent } from "@/lib/execution_events";
import {
  formatActionCommand,
  formatStepLabel,
  transcriptLineFromActionResult,
} from "@/lib/transcript";

import type { RunResponse } from "../lib/api";

type ExecutionConsolePanelProps = {
  runs: RunResponse[];
  isBusy: boolean;
  /** Run whose live `execution.action.*` stream feeds the panel (E64-S1). */
  activeRunId?: string | null;
};

type ConsoleState = "running" | "completed" | "cancelled" | "failed";

type ConsoleEntry = {
  id: string;
  labelKey: "executionConsole.runTypePlanExecution" | "executionConsole.runTypeAgent";
  /** Plain-language step annotation (E43-S3), e.g. "Creating main.py". */
  stepLabel: string;
  command: string;
  output: string;
  state: ConsoleState;
  exitCode?: number;
  /** Originating agent (E64-S2); absent on pre-E64 events. */
  sourceAgent?: string;
  /** Output hit the backend cap (E64-S2); absent on pre-E64 events. */
  truncated?: boolean;
};

/** One raw `ExecutionResult.to_dict()` entry, as carried in `result.metadata.actions[]`. */
type ActionResultRecord = {
  action_id: string;
  type?: string;
  status: string;
  exit_code?: number | null;
  command?: string[] | null;
  path?: string | null;
  stdout?: string;
  stderr?: string;
  error?: string | null;
  diff?: string;
  truncated?: boolean;
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

function stateFromStatus(status: string | undefined, fallback: ConsoleState): ConsoleState {
  switch (status) {
    case "failed":
      return "failed";
    case "cancelled":
    case "canceled":
      return "cancelled";
    case "running":
    case "pending":
    case "started":
      return "running";
    case "succeeded":
    case "completed":
      return "completed";
    default:
      return fallback;
  }
}

function labelKeyFor(runType: string | undefined) {
  return runType === "plan_execution"
    ? ("executionConsole.runTypePlanExecution" as const)
    : ("executionConsole.runTypeAgent" as const);
}

/**
 * Build one entry per real action from the polled runs (E43-S2). A task that
 * dispatched no action produces nothing (E64-S1): the panel is a record of
 * operations, never the task's model-written description.
 */
function entriesFromRuns(runs: RunResponse[]): ConsoleEntry[] {
  return runs.flatMap((run) =>
    run.results.flatMap((result) => {
      const taskTitle =
        typeof result.metadata?.title === "string" ? result.metadata.title : undefined;
      const sourceAgent =
        typeof result.metadata?.source_agent === "string"
          ? result.metadata.source_agent
          : result.agent;
      return actionRecords(result.metadata?.actions).map((action) => {
        const line = transcriptLineFromActionResult(action, taskTitle);
        return {
          id: action.action_id,
          labelKey: labelKeyFor(run.run_type),
          stepLabel: line.stepLabel,
          command: line.command,
          output: line.output,
          state: stateFromStatus(action.status, "completed"),
          exitCode: typeof action.exit_code === "number" ? action.exit_code : undefined,
          sourceAgent,
          truncated: action.truncated === true ? true : undefined,
        };
      });
    })
  );
}

function compareFrameIds(a: string | null, b: string | null): number {
  if (a === b) {
    return 0;
  }
  if (a === null) {
    return 1;
  }
  if (b === null) {
    return -1;
  }
  const na = Number(a);
  const nb = Number(b);
  return Number.isFinite(na) && Number.isFinite(nb) ? na - nb : a.localeCompare(b);
}

type StreamAccumulator = {
  entry: ConsoleEntry;
  firstFrameId: string | null;
  chunks: { stdout: Map<number, string>; stderr: Map<number, string> };
  final: boolean;
};

/**
 * Collapse the active run's `execution.action.*` events into one entry per
 * `actionId` (started + terminal merge; output chunks append by `seq` until
 * the terminal event's full output replaces them), sorted by SSE frame id.
 */
function entriesFromStream(
  events: ExecutionActionEvent[],
  labelKey: ConsoleEntry["labelKey"]
): ConsoleEntry[] {
  const byAction = new Map<string, StreamAccumulator>();
  for (const event of events) {
    let acc = byAction.get(event.actionId);
    if (!acc) {
      acc = {
        entry: {
          id: event.actionId,
          labelKey,
          stepLabel: formatStepLabel(event.stepLabel, event.taskId),
          command: formatActionCommand({
            actionId: event.actionId,
            type: event.actionType,
            command: event.command,
            path: event.path,
          }),
          output: "",
          state: "running",
        },
        firstFrameId: event.frameId,
        chunks: { stdout: new Map(), stderr: new Map() },
        final: false,
      };
      byAction.set(event.actionId, acc);
    }
    if (compareFrameIds(event.frameId, acc.firstFrameId) < 0) {
      acc.firstFrameId = event.frameId;
    }
    const entry = acc.entry;
    if (event.sourceAgent) {
      entry.sourceAgent = event.sourceAgent;
    }
    if (event.type === "execution.action.output") {
      if (event.stream && event.chunk !== undefined && !acc.final) {
        acc.chunks[event.stream].set(event.seq ?? acc.chunks[event.stream].size, event.chunk);
      }
      continue;
    }
    if (event.stepLabel) {
      entry.stepLabel = event.stepLabel;
    }
    if (event.command || event.path || event.actionType) {
      entry.command = formatActionCommand({
        actionId: event.actionId,
        type: event.actionType,
        command: event.command,
        path: event.path,
      });
    }
    if (event.type === "execution.action.started") {
      continue;
    }
    const failed = event.type === "execution.action.failed";
    entry.state = stateFromStatus(event.status, failed ? "failed" : "completed");
    entry.exitCode = event.exitCode;
    entry.truncated = event.truncated;
    acc.final = true;
    entry.output = [event.stdout, event.stderr, failed ? event.error : ""].filter(Boolean).join("\n");
  }
  return Array.from(byAction.values())
    .sort((x, y) => compareFrameIds(x.firstFrameId, y.firstFrameId))
    .map((acc) => {
      if (!acc.final) {
        const joined = (parts: Map<number, string>) =>
          Array.from(parts.entries()).sort(([x], [y]) => x - y).map(([, chunk]) => chunk).join("");
        acc.entry.output = [joined(acc.chunks.stdout), joined(acc.chunks.stderr)].filter(Boolean).join("\n");
      }
      return acc.entry;
    });
}

/**
 * Merge the live stream (complete for the active run, since a cursor-less
 * stream replays the run's history) with polled history for other runs. When
 * the stream errored, polled history covers the active run too (E64-S1-T3).
 * One entry per `actionId`; the stream wins on conflict.
 */
export function buildConsoleEntries(
  runs: RunResponse[],
  events: ExecutionActionEvent[],
  activeRunId: string | null,
  streamFailed: boolean
): ConsoleEntry[] {
  const polledRuns = streamFailed ? runs : runs.filter((run) => run.run_id !== activeRunId);
  const activeRun = runs.find((run) => run.run_id === activeRunId);
  const streamed = entriesFromStream(events, labelKeyFor(activeRun?.run_type));
  const streamedIds = new Set(streamed.map((entry) => entry.id));
  const polled = entriesFromRuns(polledRuns).filter((entry) => !streamedIds.has(entry.id));
  return [...polled, ...streamed];
}

function stateLabelKey(state: ConsoleState) {
  return `executionConsole.state${state[0].toUpperCase()}${state.slice(1)}` as
    | "executionConsole.stateRunning"
    | "executionConsole.stateCompleted"
    | "executionConsole.stateCancelled"
    | "executionConsole.stateFailed";
}

export function ExecutionConsolePanel({ runs, isBusy, activeRunId = null }: ExecutionConsolePanelProps) {
  const { t } = useTranslations();
  const { events, streamStatus } = useExecutionActionLog(activeRunId);
  const entries = buildConsoleEntries(runs, events, activeRunId, streamStatus === "error");

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
                <Badge variant="secondary">{t(stateLabelKey(entry.state))}</Badge>
              </div>
              <p className="text-sm font-semibold text-ds-fg">{entry.stepLabel}</p>
              <code className="font-mono text-[13px] text-ds-fg-2">{entry.command}</code>
              {entry.sourceAgent || entry.exitCode !== undefined ? (
                <p className="text-xs text-ds-fg-3">
                  {entry.sourceAgent ? `${t("executionConsole.agent")}: ${entry.sourceAgent}` : null}
                  {entry.sourceAgent && entry.exitCode !== undefined ? " · " : null}
                  {entry.exitCode !== undefined ? `${t("executionConsole.exitCode")}: ${entry.exitCode}` : null}
                </p>
              ) : null}
              <pre className="overflow-x-auto whitespace-pre-wrap rounded-ds-sm bg-ds-bg-4 p-3 font-mono text-xs text-ds-fg-2">
                {entry.output}
              </pre>
              {entry.truncated ? (
                <p className="text-xs text-ds-fg-3">{t("executionConsole.truncated")}</p>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

export default ExecutionConsolePanel;
