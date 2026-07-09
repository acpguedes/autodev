"use client";

import * as React from "react";

import { useShellHeader } from "@/components/shell/ShellProvider";
import { SessionRow } from "@/components/sessions/SessionRow";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "@/lib/use-toast";
import { createSessionV2, listSessionRunsV2, listSessionsV2, type SessionV2 } from "@/lib/api_v2";

/** Per-session run summary (count + last-run time) keyed by session id. */
type RunSummary = { runCount: number; lastRunAt: string | null };

/**
 * Fetch the most recent run for a session to derive its run count and
 * last-run timestamp. Backend `list_runs` implementations order results
 * newest-first, so `items[0]` is the most recent run and `page.total` is
 * the total run count — a single page-1 request is sufficient per session.
 *
 * @param sessionId - Session identifier.
 * @returns The run count and last-run timestamp, or a zeroed summary if the
 *   request fails (e.g. the session has no runs yet).
 */
async function fetchRunSummary(sessionId: string): Promise<RunSummary> {
  try {
    const runs = await listSessionRunsV2(sessionId, 1, 0);
    return {
      runCount: runs.page.total,
      lastRunAt: runs.items[0]?.created_at ?? null,
    };
  } catch {
    return { runCount: 0, lastRunAt: null };
  }
}

/**
 * Sessions screen: lists control-plane sessions with search, run counts,
 * relative last-run time, live status, and a create form; each row links to
 * the session detail screen and offers a "reopen as chat" action.
 *
 * @returns The sessions list page.
 */
export default function SessionsPage() {
  useShellHeader({
    title: "Sessions",
    subtitle: "Create sessions and follow their runs, traces, and live event streams.",
  });

  const [sessions, setSessions] = React.useState<SessionV2[] | null>(null);
  const [runSummaries, setRunSummaries] = React.useState<Record<string, RunSummary>>({});
  const [error, setError] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");
  const [goal, setGoal] = React.useState("");
  const [creating, setCreating] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const list = await listSessionsV2();
      setSessions(list.items);
      setError(null);
      setRunSummaries({});
      const entries = await Promise.all(
        list.items.map(async (session) => {
          const summary = await fetchRunSummary(session.session_id);
          return [session.session_id, summary] as const;
        })
      );
      setRunSummaries(Object.fromEntries(entries));
    } catch {
      setSessions([]);
      setError("Sessions endpoint unavailable. Start the backend to load sessions.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = goal.trim();
    if (!trimmed) {
      return;
    }
    setCreating(true);
    try {
      const session = await createSessionV2(trimmed);
      setGoal("");
      toast({ title: "Session created", description: session.session_id });
      await load();
    } catch {
      toast({
        title: "Could not create session",
        description: "The control plane rejected the request or is unavailable.",
        variant: "destructive",
      });
    } finally {
      setCreating(false);
    }
  }

  const normalizedQuery = query.trim().toLowerCase();
  const filtered = (sessions ?? []).filter(
    (session) =>
      !normalizedQuery ||
      session.goal.toLowerCase().includes(normalizedQuery) ||
      session.session_id.toLowerCase().includes(normalizedQuery)
  );

  return (
    <div className="flex flex-col gap-6 p-8">
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Sessions</CardTitle>
            <CardDescription>
              Create sessions and follow their runs, traces, and live event streams.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex flex-wrap items-center gap-2" onSubmit={handleCreate}>
              <label htmlFor="session-goal" className="sr-only">
                Goal for the new session
              </label>
              <Input
                id="session-goal"
                className="max-w-md"
                placeholder="Describe a goal to start a new session"
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
              />
              <Button type="submit" disabled={creating || goal.trim().length === 0}>
                {creating ? "Creating…" : "New session"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>All sessions</CardTitle>
            <CardDescription>
              {sessions === null
                ? "Loading sessions from the control plane…"
                : `${filtered.length} of ${sessions.length} sessions`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label htmlFor="session-search" className="sr-only">
                Search sessions
              </label>
              <Input
                id="session-search"
                className="max-w-md"
                type="search"
                placeholder="Search by goal or session id"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>

            {sessions === null ? (
              <div className="space-y-2" aria-hidden="true">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-2/3" />
              </div>
            ) : filtered.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {error ?? "No sessions match the current search."}
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Goal</TableHead>
                    <TableHead>Session id</TableHead>
                    <TableHead>Runs</TableHead>
                    <TableHead>Last run</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Reopen</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((session) => {
                    const summary = runSummaries[session.session_id];
                    return (
                      <SessionRow
                        key={session.session_id}
                        sessionId={session.session_id}
                        goal={session.goal}
                        status={session.status}
                        runCount={summary ? summary.runCount : null}
                        lastRunAt={summary ? summary.lastRunAt : null}
                      />
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
