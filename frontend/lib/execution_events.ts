"use client";

/**
 * Real-time `execution.action.*` event stream for one run (E14-S5-T2).
 *
 * Reuses the E9-S2 SSE transport primitives (`runEventsStreamUrl`,
 * `parseSseBuffer`) the exact way `components/chat/useRunTimeline.ts`
 * already does, but does **not** extend `lib/timeline.ts`: that module's
 * `applyTimelineEvent` folds events into the four fixed
 * planning/analysis/patch/validation stages
 * (`RunTimelineStepData = {stepKey, actorRole, status, output}`), which
 * `execution.action.*` events don't map onto (different payload shape, no
 * stage). This module renders a flat, real-time action log instead.
 */

import * as React from "react";

import { parseSseBuffer, runEventsStreamUrl } from "@/lib/api_v2";

/** Every `execution.action.*` event type, used as the SSE `types=` filter. */
export const EXECUTION_ACTION_EVENT_TYPES: readonly string[] = [
  "execution.action.started",
  "execution.action.completed",
  "execution.action.failed",
];

/** One decoded `execution.action.*` event. */
export interface ExecutionActionEvent {
  type: string;
  actionId: string;
  taskId: string;
  status?: string;
  exitCode?: number;
  error?: string;
  receivedAt: string;
}

/**
 * Validate and decode the JSON payload of an `execution.action.*` SSE frame.
 *
 * Input is validated at the boundary: malformed JSON or a payload missing
 * the required fields returns `null` instead of throwing.
 *
 * @param eventType - The SSE `event:` field value.
 * @param raw - The SSE frame's `data` text.
 * @returns The decoded event, or `null` when invalid or not an
 *   `execution.action.*` type.
 */
export function parseExecutionActionEvent(eventType: string, raw: string): ExecutionActionEvent | null {
  if (!eventType.startsWith("execution.action.")) {
    return null;
  }
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
  if (typeof record.actionId !== "string" || typeof record.taskId !== "string") {
    return null;
  }
  return {
    type: eventType,
    actionId: record.actionId,
    taskId: record.taskId,
    status: typeof record.status === "string" ? record.status : undefined,
    exitCode: typeof record.exitCode === "number" ? record.exitCode : undefined,
    error: typeof record.error === "string" ? record.error : undefined,
    receivedAt: new Date().toISOString(),
  };
}

/** Connection status of the execution-action SSE subscription. */
export type ExecutionLogStreamStatus = "idle" | "connecting" | "open" | "closed" | "error";

/** Return value of {@link useExecutionActionLog}. */
export interface ExecutionActionLogResult {
  events: ExecutionActionEvent[];
  streamStatus: ExecutionLogStreamStatus;
}

/**
 * Subscribe to a run's `execution.action.*` SSE events (E14-S5-T2).
 *
 * @param runId - Run to stream, or `null` when no run is selected.
 * @returns The accumulated events (newest last) and the connection status.
 */
export function useExecutionActionLog(runId: string | null): ExecutionActionLogResult {
  const [events, setEvents] = React.useState<ExecutionActionEvent[]>([]);
  const [streamStatus, setStreamStatus] = React.useState<ExecutionLogStreamStatus>("idle");

  React.useEffect(() => {
    setEvents([]);
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
          runEventsStreamUrl(runId as string, { types: [...EXECUTION_ACTION_EVENT_TYPES] }),
          {
            signal: controller.signal,
            headers: { Accept: "text/event-stream" },
            credentials: "include",
          },
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
            const parsed = parseExecutionActionEvent(frame.event, frame.data);
            if (!parsed || cancelled) {
              continue;
            }
            setEvents((current) => [...current, parsed]);
          }
        }
        if (!cancelled) {
          setStreamStatus("closed");
        }
      } catch {
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
  }, [runId]);

  return { events, streamStatus };
}
