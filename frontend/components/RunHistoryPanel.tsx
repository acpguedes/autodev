"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import { RunResponse } from "../lib/api";

export function RunHistoryPanel({ runs }: { runs: RunResponse[] }) {
  return (
    <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
      <CardHeader className="pb-3">
        <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">
          Run timeline
        </p>
        <h2 className="font-serif text-lg font-semibold text-ds-fg">Recent executions</h2>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <p className="text-sm text-ds-fg-3">No runs yet for the current session.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {runs.map((run) => (
              <article
                className="flex flex-col gap-2 rounded-ds-md border border-ds-line bg-ds-bg-3 p-4"
                key={run.run_id}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <strong className="text-sm font-semibold text-ds-fg">{run.run_type}</strong>
                    <p className="text-sm text-ds-fg-2">{run.trigger_message}</p>
                  </div>
                  <Badge variant="secondary">{run.status}</Badge>
                </div>
                <p className="text-xs text-ds-fg-3">
                  State: {run.current_state} · Steps: {run.steps.length} · Created: {run.created_at}
                </p>
                <ol className="flex flex-col gap-1">
                  {run.steps.map((step) => (
                    <li
                      className="flex items-center justify-between gap-2 text-xs"
                      key={`${run.run_id}-${step.step_key}`}
                    >
                      <span className="text-ds-fg-2">{step.agent}</span>
                      <span className="text-ds-fg-3">{step.status}</span>
                    </li>
                  ))}
                </ol>
              </article>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default RunHistoryPanel;
