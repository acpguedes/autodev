// Client-side mirror of the E16-S1 run-timeline taxonomy
// (backend/api/timeline_roles.py + backend/events/catalog.py): the four
// timeline stages, the `run.timeline.*` SSE event types that carry them,
// and the canonical agent-role labels used by the chat's role tags.

import type { RunStepV2 } from "./api_v2";

/** The four live-timeline stages, in execution order (E16-S1-T2). */
export const TIMELINE_STAGES = ["planning", "analysis", "patch", "validation"] as const;

/** One of the four canonical timeline stages. */
export type TimelineStage = (typeof TIMELINE_STAGES)[number];

/** SSE event type emitted for each timeline stage (`run.timeline.<stage>`). */
export const TIMELINE_EVENT_TYPE_BY_STAGE: Record<TimelineStage, string> = {
  planning: "run.timeline.planning",
  analysis: "run.timeline.analysis",
  patch: "run.timeline.patch",
  validation: "run.timeline.validation",
};

/** Every `run.timeline.*` event type, used as the SSE `types=` filter. */
export const TIMELINE_EVENT_TYPES: readonly string[] = TIMELINE_STAGES.map(
  (stage) => TIMELINE_EVENT_TYPE_BY_STAGE[stage]
);

/**
 * Canonical agent role -> timeline stage mapping (E16-S1-T3). Navigator and
 * analyzer share the analysis stage; architect/devops/responder do not map
 * onto the four-stage timeline.
 */
export const AGENT_ROLE_TO_STAGE: Readonly<Record<string, TimelineStage>> = {
  planner: "planning",
  navigator: "analysis",
  analyzer: "analysis",
  coder: "patch",
  validator: "validation",
};

/** Display labels for the eight canonical E2 agent roles. */
export const AGENT_ROLE_LABELS: Readonly<Record<string, string>> = {
  planner: "Planner",
  navigator: "Navigator",
  analyzer: "Analyzer",
  architect: "Architect",
  coder: "Coder",
  devops: "DevOps",
  validator: "Validator",
  responder: "Responder",
};

/**
 * Resolve the display label for an agent role.
 *
 * @param role - Canonical role id (e.g. `"planner"`), any casing.
 * @returns The known label, or the raw role capitalized as a fallback.
 */
export function agentRoleLabel(role: string): string {
  const normalized = role.trim().toLowerCase();
  const known = AGENT_ROLE_LABELS[normalized];
  if (known) {
    return known;
  }
  return normalized.length > 0 ? normalized[0].toUpperCase() + normalized.slice(1) : "Agent";
}

/**
 * Map an agent role to its timeline stage.
 *
 * @param role - Canonical role id, any casing.
 * @returns The stage, or `null` when the role is not on the timeline.
 */
export function timelineStageForAgentRole(role: string): TimelineStage | null {
  return AGENT_ROLE_TO_STAGE[role.trim().toLowerCase()] ?? null;
}

/**
 * Map a `run.timeline.*` SSE event type back to its stage.
 *
 * @param eventType - The SSE `event:` field value.
 * @returns The stage, or `null` for non-timeline events.
 */
export function timelineStageForEventType(eventType: string): TimelineStage | null {
  for (const stage of TIMELINE_STAGES) {
    if (TIMELINE_EVENT_TYPE_BY_STAGE[stage] === eventType) {
      return stage;
    }
  }
  return null;
}

/** Rendered status of a timeline stage. */
export type TimelineStageStatus = "idle" | "running" | "done" | "failed";

/** Display state of one timeline stage. */
export type TimelineStageState = {
  /** Which of the four stages this entry represents. */
  stage: TimelineStage;
  /** Current rendered status. */
  status: TimelineStageStatus;
  /** Role of the agent driving the stage, when known. */
  actorRole: string | null;
  /** Monospace stdout/log excerpt for the stage ("" when none). */
  output: string;
};

/** Shared payload of every `run.timeline.*` event (RunTimelineStepData). */
export type RunTimelineStepData = {
  stepKey: string;
  actorRole: string;
  status: string;
  output: string;
};

/**
 * Normalize a backend step/event status string into a rendered status.
 *
 * @param status - Raw status (e.g. `"completed"`, `"failed"`, `"running"`).
 * @returns The rendered stage status; unknown values map to `"running"` so
 *   an in-flight stage is never rendered as silently idle.
 */
export function normalizeStageStatus(status: string): TimelineStageStatus {
  const normalized = status.trim().toLowerCase();
  if (["completed", "complete", "done", "success", "succeeded", "ok"].includes(normalized)) {
    return "done";
  }
  if (["failed", "error", "errored", "cancelled", "canceled"].includes(normalized)) {
    return "failed";
  }
  if (normalized === "" || normalized === "idle" || normalized === "pending") {
    return "idle";
  }
  return "running";
}

/**
 * Build the initial, all-idle timeline.
 *
 * @returns One idle {@link TimelineStageState} per stage, in order.
 */
export function emptyTimeline(): TimelineStageState[] {
  return TIMELINE_STAGES.map((stage) => ({
    stage,
    status: "idle",
    actorRole: null,
    output: "",
  }));
}

/**
 * Seed the timeline from a run's recorded trace steps (`RunStepV2[]`).
 *
 * Used to render a turn's timeline from the synchronous turn response, so
 * the panel is correct even before (or without) any SSE event arriving.
 *
 * @param steps - Trace steps from a `/v2` run or turn document.
 * @returns The stage states derived from the steps.
 */
export function timelineFromRunSteps(steps: readonly RunStepV2[]): TimelineStageState[] {
  const states = emptyTimeline();
  for (const step of steps) {
    const stage = timelineStageForAgentRole(step.agent);
    if (!stage) {
      continue;
    }
    const state = states.find((entry) => entry.stage === stage);
    if (!state) {
      continue;
    }
    const status = normalizeStageStatus(step.status);
    // Never regress a non-idle stage back to idle (navigator + analyzer
    // both land on "analysis"; the later, more advanced step wins).
    if (status !== "idle") {
      state.status = status;
    }
    state.actorRole = step.agent;
  }
  return states;
}

/**
 * Validate and decode the JSON payload of a `run.timeline.*` SSE frame.
 *
 * Input is validated at the boundary: malformed JSON or a payload missing
 * the RunTimelineStepData fields returns `null` instead of throwing.
 *
 * @param raw - The SSE frame's `data` text.
 * @returns The decoded payload, or `null` when invalid.
 */
export function parseRunTimelineStepData(raw: string): RunTimelineStepData | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.stepKey !== "string" ||
    typeof record.actorRole !== "string" ||
    typeof record.status !== "string" ||
    typeof record.output !== "string"
  ) {
    return null;
  }
  return {
    stepKey: record.stepKey,
    actorRole: record.actorRole,
    status: record.status,
    output: record.output,
  };
}

/**
 * Apply one decoded timeline event to the current stage states.
 *
 * @param states - Current stage states (not mutated).
 * @param eventType - The SSE `event:` field (`run.timeline.<stage>`).
 * @param data - The decoded event payload.
 * @returns A new state array with the matching stage updated; the input
 *   array is returned unchanged for non-timeline event types.
 */
export function applyTimelineEvent(
  states: readonly TimelineStageState[],
  eventType: string,
  data: RunTimelineStepData
): TimelineStageState[] {
  const stage = timelineStageForEventType(eventType);
  if (!stage) {
    return [...states];
  }
  return states.map((state) =>
    state.stage === stage
      ? {
          ...state,
          status: normalizeStageStatus(data.status),
          actorRole: data.actorRole,
          output: data.output,
        }
      : state
  );
}
