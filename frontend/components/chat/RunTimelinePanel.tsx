"use client";

import * as React from "react";

import type { RunStepV2 } from "@/lib/api_v2";
import { useTranslations } from "@/lib/i18n";
import type { TimelineStage, TimelineStageStatus } from "@/lib/timeline";

import { ExecutionTimeline } from "./ExecutionTimeline";
import { useRunTimeline } from "./useRunTimeline";

/** Props for {@link RunTimelinePanel}. */
export type RunTimelinePanelProps = {
  /** The active run to stream, or `null` before the first turn. */
  runId: string | null;
  /** Trace steps of the active run, used to seed the timeline. */
  seedSteps: readonly RunStepV2[];
  /** True while a turn is being created (run id not yet known). */
  pending: boolean;
};

/**
 * Execution-panel content for the chat view: streams the active run's
 * `run.timeline.*` events and renders the four-stage timeline with
 * localized labels. While a turn is in flight and the run id is still
 * unknown, the planning stage is shown as running.
 *
 * @param props - See {@link RunTimelinePanelProps}.
 * @returns The localized timeline panel.
 */
export function RunTimelinePanel({
  runId,
  seedSteps,
  pending,
}: RunTimelinePanelProps): React.JSX.Element {
  const { t } = useTranslations();
  const { stages } = useRunTimeline(runId, seedSteps);

  const stageLabels: Record<TimelineStage, string> = {
    planning: t("chat.timeline.planning"),
    analysis: t("chat.timeline.analysis"),
    patch: t("chat.timeline.patch"),
    validation: t("chat.timeline.validation"),
  };
  const statusLabels: Record<TimelineStageStatus, string> = {
    idle: t("chat.timeline.statusIdle"),
    running: t("chat.timeline.statusRunning"),
    done: t("chat.timeline.statusDone"),
    failed: t("chat.timeline.statusFailed"),
  };

  const displayStages =
    pending && !runId
      ? stages.map((stage) =>
          stage.stage === "planning" ? { ...stage, status: "running" as const } : stage
        )
      : stages;

  return (
    <ExecutionTimeline
      stages={displayStages}
      stageLabels={stageLabels}
      statusLabels={statusLabels}
      idleHint={t("chat.timeline.idleHint")}
    />
  );
}

export default RunTimelinePanel;
