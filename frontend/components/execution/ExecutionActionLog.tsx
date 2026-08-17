"use client";

import { useTranslations } from "@/lib/i18n";
import { useExecutionActionLog, type ExecutionActionEvent } from "@/lib/execution_events";

function eventTone(event: ExecutionActionEvent): string {
  if (event.type === "execution.action.failed") {
    return "text-ds-danger";
  }
  if (event.type === "execution.action.completed") {
    return "text-ds-fg";
  }
  return "text-ds-fg-2";
}

export interface ExecutionActionLogProps {
  /** Run whose `execution.action.*` events to stream, or `null` for none selected. */
  runId: string | null;
}

/**
 * Real-time execution-action log (E14-S5-T2): one line per
 * `execution.action.started`/`.completed`/`.failed` event, via the E9-S2
 * SSE transport (`lib/execution_events.ts`).
 */
export function ExecutionActionLog({ runId }: ExecutionActionLogProps) {
  const { t } = useTranslations();
  const { events, streamStatus } = useExecutionActionLog(runId);

  if (!runId) {
    return <p className="text-sm text-ds-fg-2">{t("execution.log.noRun")}</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-ds-fg-2">{t(`execution.log.status.${streamStatus}`)}</p>
      {events.length === 0 ? (
        <p className="text-sm text-ds-fg-2">{t("execution.log.empty")}</p>
      ) : (
        <ul
          className="flex max-h-64 flex-col gap-1 overflow-y-auto rounded-ds-md border border-ds-line bg-ds-bg p-3 font-mono text-xs"
          aria-live="polite"
        >
          {events.map((event, position) => (
            <li key={`${event.actionId}-${event.type}-${position}`} className={eventTone(event)}>
              {event.type} · {event.taskId} · {event.actionId}
              {event.status ? ` · ${event.status}` : ""}
              {typeof event.exitCode === "number" ? ` · exit ${event.exitCode}` : ""}
              {event.error ? ` · ${event.error}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
