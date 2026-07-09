"use client";

import * as React from "react";

import { parseSseBuffer, runEventsStreamUrl, type RunStepV2 } from "@/lib/api_v2";
import {
  TIMELINE_EVENT_TYPES,
  applyTimelineEvent,
  emptyTimeline,
  parseRunTimelineStepData,
  timelineFromRunSteps,
  type TimelineStageState,
} from "@/lib/timeline";

/** Connection status of the timeline's SSE subscription. */
export type TimelineStreamStatus = "idle" | "connecting" | "open" | "closed" | "error";

/** Return value of {@link useRunTimeline}. */
export type RunTimelineResult = {
  /** The four stage states, in execution order. */
  stages: TimelineStageState[];
  /** Live status of the SSE subscription. */
  streamStatus: TimelineStreamStatus;
};

/**
 * Subscribe to a run's `run.timeline.*` SSE events and fold them into the
 * four-stage timeline state (E17-S1-T3, wired to E16-S1).
 *
 * Reuses the `RunEventStream` transport pattern — `fetch` + incremental
 * `parseSseBuffer` decoding instead of `EventSource`, because the backend
 * uses named event types. The timeline is seeded from the turn's recorded
 * trace steps so it renders correctly from the synchronous turn response,
 * and any streamed `run.timeline.*` event (including replayed history —
 * the stream replays from the start when no cursor is given) refines it.
 *
 * @param runId - Run to stream, or `null` when no run is active.
 * @param seedSteps - Trace steps from the turn document used as the
 *   authoritative initial state.
 * @returns The stage states and the SSE connection status.
 */
export function useRunTimeline(
  runId: string | null,
  seedSteps: readonly RunStepV2[]
): RunTimelineResult {
  const [stages, setStages] = React.useState<TimelineStageState[]>(() =>
    runId ? timelineFromRunSteps(seedSteps) : emptyTimeline()
  );
  const [streamStatus, setStreamStatus] = React.useState<TimelineStreamStatus>("idle");

  React.useEffect(() => {
    setStages(runId ? timelineFromRunSteps(seedSteps) : emptyTimeline());
    if (!runId) {
      setStreamStatus("idle");
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    async function consume(): Promise<void> {
      setStreamStatus("connecting");
      try {
        const response = await fetch(
          runEventsStreamUrl(runId as string, { types: [...TIMELINE_EVENT_TYPES] }),
          { signal: controller.signal, headers: { Accept: "text/event-stream" } }
        );
        if (!response.ok || !response.body) {
          if (!cancelled) {
            setStreamStatus("error");
          }
          return;
        }
        if (!cancelled) {
          setStreamStatus("open");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          const { frames, rest } = parseSseBuffer(buffer);
          buffer = rest;
          for (const frame of frames) {
            if (!frame.event) {
              continue;
            }
            const data = parseRunTimelineStepData(frame.data);
            if (!data) {
              continue;
            }
            const eventType = frame.event;
            if (!cancelled) {
              setStages((current) => applyTimelineEvent(current, eventType, data));
            }
          }
        }
        if (!cancelled) {
          setStreamStatus("closed");
        }
      } catch {
        // AbortError on unmount/run-change is expected; anything else is a
        // transport failure. Either way the seeded state stays rendered.
        if (!cancelled) {
          setStreamStatus(controller.signal.aborted ? "closed" : "error");
        }
      }
    }

    void consume();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [runId, seedSteps]);

  return { stages, streamStatus };
}

export default useRunTimeline;
