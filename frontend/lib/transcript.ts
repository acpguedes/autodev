// Shared terminal-style transcript rendering (E43-S2).
//
// One formatter for `execution.action.*` payloads, used by both the session
// detail page's Live-stream tab and the Chat Execution panel, so they can't
// drift into two different renderings of the same events again (E42-S5 only
// fixed one of the two surfaces).

/** The `execution.action.*` event types a transcript can render as a line. */
export const TRANSCRIPT_ACTION_EVENT_TYPES = [
  "execution.action.started",
  "execution.action.completed",
  "execution.action.failed",
] as const;

export type TranscriptActionEventType = (typeof TRANSCRIPT_ACTION_EVENT_TYPES)[number];

/** Visual tone of one rendered transcript line. */
export type TranscriptTone = "pending" | "success" | "error";

/** One terminal-style transcript line: a command prompt plus its real output. */
export type TranscriptLine = {
  /** Stable key for list rendering. */
  key: string;
  /** The `$ <command>` (or `$ write <path>`) prompt line. */
  command: string;
  /** Real stdout/stderr/error beneath the prompt; empty when not known yet. */
  output: string;
  tone: TranscriptTone;
};

/** Shape common to the three `execution.action.*` payloads (E43-S2 fields optional for forward-compat). */
export type ExecutionActionEventData = {
  actionId: string;
  taskId?: string;
  type?: string;
  status?: string;
  exitCode?: number;
  error?: string;
  command?: string[] | null;
  path?: string | null;
  stdout?: string;
  stderr?: string;
};

/**
 * Build the `$ ...` prompt line for one action.
 *
 * @param data - The action event's decoded payload.
 * @returns A real command line when known, otherwise a generic fallback
 *   naming the action so the transcript never renders a blank prompt.
 */
export function formatActionCommand(data: ExecutionActionEventData): string {
  if (data.command && data.command.length > 0) {
    return `$ ${data.command.join(" ")}`;
  }
  if (data.path) {
    return `$ write ${data.path}`;
  }
  return `$ ${data.type ?? "action"} ${data.actionId}`;
}

/**
 * Turn one decoded `execution.action.*` SSE frame into a transcript line.
 *
 * @param eventType - The SSE `event:` field.
 * @param data - The decoded JSON payload.
 * @returns The rendered line, or `null` if `eventType` is not a recognized
 *   action event (callers fall back to their own generic rendering).
 */
export function transcriptLineFromActionEvent(
  eventType: string,
  data: ExecutionActionEventData
): TranscriptLine | null {
  if (!TRANSCRIPT_ACTION_EVENT_TYPES.includes(eventType as TranscriptActionEventType)) {
    return null;
  }
  const command = formatActionCommand(data);
  const key = `${data.actionId}-${eventType}`;

  if (eventType === "execution.action.started") {
    return { key, command, output: "", tone: "pending" };
  }
  if (eventType === "execution.action.failed") {
    const output = [data.stdout, data.stderr, data.error].filter(Boolean).join("\n");
    return { key, command, output, tone: "error" };
  }
  const output = [data.stdout, data.stderr].filter(Boolean).join("\n");
  return { key, command, output, tone: "success" };
}

/**
 * Build a transcript line from one action's real, already-captured result
 * (the synchronous turn/run response's `metadata.actions[]` entries), rather
 * than a live SSE event -- same shared formatting, different data source.
 *
 * @param action - One `ExecutionResult.to_dict()` entry.
 * @returns The rendered transcript line.
 */
export function transcriptLineFromActionResult(action: {
  action_id: string;
  status: string;
  command?: string[] | null;
  path?: string | null;
  stdout?: string;
  stderr?: string;
  error?: string | null;
  diff?: string;
}): TranscriptLine {
  const command = formatActionCommand({
    actionId: action.action_id,
    command: action.command,
    path: action.path,
  });
  const failed = action.status === "failed";
  const output =
    [action.stdout, action.stderr, failed ? action.error ?? "" : "", action.diff]
      .filter(Boolean)
      .join("\n") || (failed ? "" : "(no output)");
  return {
    key: action.action_id,
    command,
    output,
    tone: failed ? "error" : "success",
  };
}
