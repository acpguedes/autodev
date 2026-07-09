import Link from "next/link";
import * as React from "react";

import { StatusGlowDot, statusToTone } from "@/components/StatusGlowDot";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import { formatRelativeTime } from "@/lib/utils";

export interface SessionRowProps {
  /** Session identifier. */
  sessionId: string;
  /** The operator's goal for the session. */
  goal: string;
  /** Raw session status string from the control plane. */
  status: string;
  /** Total historical runs for this session, or `null` while still loading. */
  runCount: number | null;
  /** ISO timestamp of the session's most recent run, or `null` if none yet. */
  lastRunAt: string | null;
}

/**
 * One row in the sessions table: goal (links to the session detail screen),
 * session id, run count, relative time of the last run, a status glow dot
 * (whose state is also conveyed via a visible text label for color-blind and
 * screen-reader users), and a "reopen as chat" action that hands the session
 * back to the chat screen via a `?sessionId=` query parameter.
 *
 * @param props - Session summary fields backing this row.
 * @returns The rendered table row.
 */
export function SessionRow({
  sessionId,
  goal,
  status,
  runCount,
  lastRunAt,
}: SessionRowProps): React.JSX.Element {
  return (
    <TableRow>
      <TableCell className="max-w-md truncate font-medium">
        <Link
          className="underline-offset-4 hover:underline focus-visible:underline"
          href={`/sessions/${sessionId}`}
        >
          {goal || "(no goal)"}
        </Link>
      </TableCell>
      <TableCell className="font-mono text-xs">{sessionId}</TableCell>
      <TableCell>{runCount === null ? "…" : runCount}</TableCell>
      <TableCell className="text-ds-fg-2">{formatRelativeTime(lastRunAt)}</TableCell>
      <TableCell>
        <StatusGlowDot tone={statusToTone(status)} label={status || "unknown"} />
      </TableCell>
      <TableCell className="text-right">
        <Button variant="outline" size="sm" asChild>
          <Link href={`/?sessionId=${encodeURIComponent(sessionId)}`}>Open chat</Link>
        </Button>
      </TableCell>
    </TableRow>
  );
}

export default SessionRow;
