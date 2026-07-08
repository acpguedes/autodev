"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { parseSseBuffer, runEventsStreamUrl, type SseFrame } from "@/lib/api_v2";

/** Maximum number of events retained in the visible stream log. */
const MAX_EVENTS = 200;

/** Connection lifecycle of the SSE consumer. */
type StreamStatus = "idle" | "connecting" | "open" | "closed" | "error";

/** One received event, decorated with a client-side reception timestamp. */
type StreamEvent = SseFrame & { receivedAt: string; key: number };

type RunEventStreamProps = {
  /** Run whose catalog events should be streamed. */
  runId: string;
  /** Optional tenant scope forwarded as the `tenantId` query parameter. */
  tenantId?: string;
};

const STATUS_LABEL: Record<StreamStatus, string> = {
  idle: "Idle",
  connecting: "Connecting…",
  open: "Live",
  closed: "Closed",
  error: "Error",
};

/**
 * Live Server-Sent-Events viewer for a run's `/v2/runs/{id}/events/stream`.
 *
 * Uses `fetch` + incremental SSE framing (instead of `EventSource`) so
 * arbitrary catalog event names are received without pre-registering
 * listeners per type. The stream stops on unmount, on run change, or when
 * the operator presses Stop.
 *
 * @param props - The run id and optional tenant scope to stream.
 * @returns The stream controls and the received-event log.
 */
export function RunEventStream({ runId, tenantId }: RunEventStreamProps) {
  const [status, setStatus] = React.useState<StreamStatus>("idle");
  const [events, setEvents] = React.useState<StreamEvent[]>([]);
  const [streaming, setStreaming] = React.useState(false);
  const abortRef = React.useRef<AbortController | null>(null);
  const counterRef = React.useRef(0);

  React.useEffect(() => {
    if (!streaming) {
      return undefined;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("connecting");

    (async () => {
      try {
        const response = await fetch(
          runEventsStreamUrl(runId, tenantId ? { tenantId } : {}),
          { signal: controller.signal, headers: { Accept: "text/event-stream" } }
        );
        if (!response.ok || !response.body) {
          setStatus("error");
          return;
        }
        setStatus("open");
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
          if (frames.length > 0) {
            const receivedAt = new Date().toLocaleTimeString();
            setEvents((previous) => {
              const next = [
                ...frames.map((frame) => ({
                  ...frame,
                  receivedAt,
                  key: counterRef.current++,
                })),
                ...previous,
              ];
              return next.slice(0, MAX_EVENTS);
            });
          }
        }
        setStatus("closed");
      } catch {
        setStatus(controller.signal.aborted ? "closed" : "error");
      }
    })();

    return () => {
      abortRef.current = null;
      controller.abort();
    };
  }, [streaming, runId, tenantId]);

  // Restart cleanly when the target run changes mid-stream.
  React.useEffect(() => {
    setEvents([]);
    setStreaming(false);
    setStatus("idle");
  }, [runId]);

  const statusVariant =
    status === "open" ? "default" : status === "error" ? "destructive" : "secondary";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          onClick={() => setStreaming(true)}
          disabled={streaming}
        >
          Start stream
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setStreaming(false)}
          disabled={!streaming}
        >
          Stop
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setEvents([])}
          disabled={events.length === 0}
        >
          Clear
        </Button>
        <Badge variant={statusVariant} aria-live="polite">
          {STATUS_LABEL[status]}
        </Badge>
      </div>

      {events.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {streaming
            ? "Waiting for events…"
            : "Start the stream to follow this run's events live."}
        </p>
      ) : (
        <ol aria-label="Run events" className="max-h-96 space-y-2 overflow-auto">
          {events.map((item) => (
            <li key={item.key} className="rounded-md border p-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{item.event ?? "message"}</Badge>
                <span className="text-xs text-muted-foreground">{item.receivedAt}</span>
                {item.id ? (
                  <span className="text-xs text-muted-foreground">cursor {item.id}</span>
                ) : null}
              </div>
              {item.data ? (
                <pre className="mt-1 overflow-auto whitespace-pre-wrap break-all text-xs text-muted-foreground">
                  {item.data}
                </pre>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export default RunEventStream;
