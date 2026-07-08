"use client";

import { useParams } from "next/navigation";
import * as React from "react";

import ChatLayout from "../../../components/ChatLayout";
import RunEventStream from "../../../components/RunEventStream";
import { Badge } from "@/components/ui/badge";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  getSessionV2,
  listSessionRunsV2,
  type RunV2,
  type SessionV2,
} from "@/lib/api_v2";
import { statusVariant } from "@/lib/utils";

/** Milliseconds between run-list refreshes while the screen is open. */
const RUNS_POLL_INTERVAL_MS = 5000;

/**
 * Trace table for one run's recorded steps.
 *
 * @param props - The run whose steps are rendered.
 * @returns The steps table, or an empty state when there is no trace yet.
 */
function RunTrace({ run }: { run: RunV2 }) {
  if (run.steps.length === 0) {
    return <p className="text-sm text-muted-foreground">No steps recorded yet.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Step</TableHead>
          <TableHead>Agent</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Attempt</TableHead>
          <TableHead>Started</TableHead>
          <TableHead>Completed</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {run.steps.map((step) => (
          <TableRow key={`${run.run_id}-${step.step_key}-${step.attempt}`}>
            <TableCell className="font-mono text-xs">{step.step_key}</TableCell>
            <TableCell>{step.agent}</TableCell>
            <TableCell>
              <Badge variant={statusVariant(step.status)}>{step.status}</Badge>
            </TableCell>
            <TableCell>{step.attempt}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{step.started_at}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{step.completed_at}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * Session detail screen: session summary and plan, run history with
 * step-level traces, a live SSE event stream per run, and the
 * conversational history.
 *
 * @returns The session detail page.
 */
export default function SessionDetailPage() {
  const params = useParams<{ sessionId: string }>();
  const sessionId = params.sessionId;

  const [session, setSession] = React.useState<SessionV2 | null>(null);
  const [runs, setRuns] = React.useState<RunV2[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = React.useState<string>("");
  const [tenantId, setTenantId] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;

    async function loadRuns() {
      try {
        const list = await listSessionRunsV2(sessionId);
        if (!cancelled) {
          setRuns(list.items);
        }
      } catch {
        if (!cancelled) {
          setRuns((previous) => previous ?? []);
        }
      }
    }

    getSessionV2(sessionId)
      .then((doc) => {
        if (!cancelled) {
          setSession(doc);
          setError(null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Session not found (or the control plane is unavailable).");
        }
      });

    void loadRuns();
    const timer = setInterval(loadRuns, RUNS_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [sessionId]);

  React.useEffect(() => {
    if (!selectedRunId && runs && runs.length > 0) {
      setSelectedRunId(runs[0].run_id);
    }
  }, [runs, selectedRunId]);

  return (
    <ChatLayout currentView="sessions">
      <div className="space-y-6">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink href="/sessions">Sessions</BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage className="font-mono text-xs">{sessionId}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        {error ? (
          <Card>
            <CardHeader>
              <CardTitle>Session unavailable</CardTitle>
              <CardDescription>{error}</CardDescription>
            </CardHeader>
          </Card>
        ) : session === null ? (
          <div className="space-y-2" aria-hidden="true">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-8 w-1/2" />
          </div>
        ) : (
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle>{session.goal || "(no goal)"}</CardTitle>
                <Badge variant={statusVariant(session.status)}>{session.status}</Badge>
              </div>
              <CardDescription>
                {session.plan.length} plan step{session.plan.length === 1 ? "" : "s"}
              </CardDescription>
            </CardHeader>
            {session.plan.length > 0 ? (
              <CardContent>
                <ol className="list-decimal space-y-1 pl-5 text-sm">
                  {session.plan.map((step, index) => (
                    <li key={`${index}-${step}`}>{step}</li>
                  ))}
                </ol>
              </CardContent>
            ) : null}
          </Card>
        )}

        <Tabs defaultValue="runs">
          <TabsList>
            <TabsTrigger value="runs">Runs &amp; traces</TabsTrigger>
            <TabsTrigger value="stream">Live stream</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
          </TabsList>

          <TabsContent value="runs" className="space-y-4">
            {runs === null ? (
              <Skeleton className="h-24 w-full" aria-hidden="true" />
            ) : runs.length === 0 ? (
              <p className="text-sm text-muted-foreground">No runs recorded for this session yet.</p>
            ) : (
              runs.map((run) => (
                <Card key={run.run_id}>
                  <CardHeader>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <CardTitle className="text-base">{run.run_type}</CardTitle>
                      <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
                    </div>
                    <CardDescription>
                      <span className="font-mono text-xs">{run.run_id}</span> · state{" "}
                      {run.current_state} · created {run.created_at}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {run.trigger_message ? (
                      <p className="text-sm text-muted-foreground">{run.trigger_message}</p>
                    ) : null}
                    <RunTrace run={run} />
                  </CardContent>
                </Card>
              ))
            )}
          </TabsContent>

          <TabsContent value="stream">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Live run events</CardTitle>
                <CardDescription>
                  Streams catalog events over SSE from /v2/runs/&#123;run_id&#125;/events/stream.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="space-y-1">
                    <label htmlFor="stream-run" className="text-sm font-medium">
                      Run
                    </label>
                    <Select value={selectedRunId} onValueChange={setSelectedRunId}>
                      <SelectTrigger id="stream-run" className="w-72">
                        <SelectValue placeholder="Pick a run to stream" />
                      </SelectTrigger>
                      <SelectContent>
                        {(runs ?? []).map((run) => (
                          <SelectItem key={run.run_id} value={run.run_id}>
                            {run.run_type} · {run.run_id}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <label htmlFor="stream-tenant" className="text-sm font-medium">
                      Tenant (optional)
                    </label>
                    <Input
                      id="stream-tenant"
                      className="w-48"
                      placeholder="tenant id"
                      value={tenantId}
                      onChange={(event) => setTenantId(event.target.value)}
                    />
                  </div>
                </div>

                {selectedRunId ? (
                  <RunEventStream runId={selectedRunId} tenantId={tenantId.trim() || undefined} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Select a run to open its live event stream.
                  </p>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="history">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Conversation history</CardTitle>
              </CardHeader>
              <CardContent>
                {!session || session.history.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No history recorded yet.</p>
                ) : (
                  <ol className="space-y-3">
                    {session.history.map((item, index) => (
                      <li key={`${index}-${item.role}`} className="rounded-md border p-3">
                        <Badge variant="outline">{item.role}</Badge>
                        <p className="mt-2 whitespace-pre-wrap text-sm">{item.content}</p>
                      </li>
                    ))}
                  </ol>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </ChatLayout>
  );
}
