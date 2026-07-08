"use client";

import Link from "next/link";
import * as React from "react";

import { useShellHeader } from "@/components/shell/ShellProvider";
import { Badge } from "@/components/ui/badge";
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
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "@/lib/use-toast";
import { createSessionV2, listSessionsV2, type SessionV2 } from "@/lib/api_v2";
import { statusVariant } from "@/lib/utils";

/**
 * Sessions screen: lists control-plane sessions with search, status badges,
 * and a create form; each row links to the session/run detail screen.
 *
 * @returns The sessions list page.
 */
export default function SessionsPage() {
  useShellHeader({
    title: "Sessions",
    subtitle: "Create sessions and follow their runs, traces, and live event streams.",
  });

  const [sessions, setSessions] = React.useState<SessionV2[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");
  const [goal, setGoal] = React.useState("");
  const [creating, setCreating] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const list = await listSessionsV2();
      setSessions(list.items);
      setError(null);
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
                    <TableHead>Plan steps</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((session) => (
                    <TableRow key={session.session_id}>
                      <TableCell className="max-w-md truncate font-medium">
                        <Link
                          className="underline-offset-4 hover:underline focus-visible:underline"
                          href={`/sessions/${session.session_id}`}
                        >
                          {session.goal || "(no goal)"}
                        </Link>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{session.session_id}</TableCell>
                      <TableCell>{session.plan.length}</TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(session.status)}>{session.status}</Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
