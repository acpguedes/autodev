"use client";

import { Loader2 } from "lucide-react";
import * as React from "react";

import {
  agentRoleLabel,
  type TimelineStage,
  type TimelineStageState,
  type TimelineStageStatus,
} from "@/lib/timeline";

/** Default English labels for the four stages (prototype wording). */
export const DEFAULT_STAGE_LABELS: Record<TimelineStage, string> = {
  planning: "Planning",
  analysis: "Repository analysis",
  patch: "Patch generation",
  validation: "Validation",
};

/** Props for {@link ExecutionTimeline}. */
export type ExecutionTimelineProps = {
  /** The four stage states, in execution order. */
  stages: readonly TimelineStageState[];
  /** Stage display labels; defaults to English prototype wording. */
  stageLabels?: Record<TimelineStage, string>;
  /** Hint shown while every stage is idle. */
  idleHint: string;
  /** Accessible status labels keyed by stage status. */
  statusLabels: Record<TimelineStageStatus, string>;
};

/** Status-dot color classes per stage status (prototype status dots). */
const DOT_CLASS: Record<TimelineStageStatus, string> = {
  idle: "bg-ds-fg-3",
  running: "bg-ds-accent animate-pulse",
  done: "bg-ds-success",
  failed: "bg-ds-danger",
};

/**
 * The live execution timeline (E17-S1-T3): the run's planning → analysis →
 * patch → validation stages with status dots, a spinner on the running
 * stage, and monospace step output, across idle/running/done/failed states.
 *
 * Purely presentational — streaming state is produced by `useRunTimeline`
 * and passed in, so the panel re-renders independently of the chat column.
 *
 * @param props - See {@link ExecutionTimelineProps}.
 * @returns The timeline list, or an idle hint when nothing has run yet.
 */
export function ExecutionTimeline({
  stages,
  stageLabels = DEFAULT_STAGE_LABELS,
  idleHint,
  statusLabels,
}: ExecutionTimelineProps): React.JSX.Element {
  const allIdle = stages.every((stage) => stage.status === "idle");

  return (
    <div className="flex flex-col gap-3 p-4">
      {allIdle ? <p className="text-[13px] leading-relaxed text-ds-fg-2">{idleHint}</p> : null}
      <ol className="flex flex-col gap-2.5">
        {stages.map((stage) => (
          <li
            key={stage.stage}
            className="rounded-ds-md border border-ds-line bg-ds-bg-3 px-3 py-2.5"
          >
            <div className="flex items-center gap-2.5">
              <span aria-hidden="true" className={`h-[9px] w-[9px] shrink-0 rounded-full ${DOT_CLASS[stage.status]}`} />
              <span className="text-[13px] font-semibold text-ds-fg">
                {stageLabels[stage.stage]}
              </span>
              {stage.actorRole ? (
                <span className="rounded-ds-sm bg-ds-accent/10 px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-[0.05em] text-ds-accent-strong">
                  {agentRoleLabel(stage.actorRole)}
                </span>
              ) : null}
              <span className="ml-auto flex items-center gap-1.5 text-[11px] text-ds-fg-3">
                {stage.status === "running" ? (
                  <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin text-ds-accent" />
                ) : null}
                {statusLabels[stage.status]}
              </span>
            </div>
            {stage.output ? (
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-ds-sm bg-ds-bg px-2.5 py-2 font-mono text-[11.5px] leading-relaxed text-ds-fg-2">
                {stage.output}
              </pre>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}

export default ExecutionTimeline;
