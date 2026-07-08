"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import { ExecutionPlanResponse } from "../lib/api";

type ExecutionPlanPanelProps = {
  executionPlan: ExecutionPlanResponse | null;
  isExecuting: boolean;
  onExecute: () => Promise<void> | void;
};

export function ExecutionPlanPanel({
  executionPlan,
  isExecuting,
  onExecute,
}: ExecutionPlanPanelProps) {
  return (
    <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
      <CardHeader className="flex-col gap-3 space-y-0 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-col gap-1">
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">
            Post-analysis workflow
          </p>
          <h2 className="font-serif text-lg font-semibold text-ds-fg">
            Step-by-step execution plan
          </h2>
          <p className="text-sm text-ds-fg-3">
            Convert the latest analysis into an ordered task list and execute each task sequentially.
          </p>
        </div>

        <Button
          variant="outline"
          type="button"
          onClick={() => void onExecute()}
          disabled={!executionPlan || executionPlan.tasks.length === 0 || isExecuting}
        >
          {isExecuting ? "Executing plan..." : "Execute plan"}
        </Button>
      </CardHeader>
      <CardContent>
        {!executionPlan ? (
          <p className="text-sm text-ds-fg-3">Loading execution plan...</p>
        ) : executionPlan.tasks.length === 0 ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm text-ds-fg-3">{executionPlan.summary}</p>
            <p className="text-sm text-ds-fg-3">
              Send a message to the agents first so the analyzer can produce the execution backlog.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1 rounded-ds-md border border-ds-line bg-ds-bg-3 p-4">
              <p className="text-sm font-medium text-ds-fg-2">Analysis summary</p>
              <p className="text-sm text-ds-fg">{executionPlan.analysis_summary}</p>
              <p className="text-sm text-ds-fg-3">{executionPlan.summary}</p>
            </div>

            <ol className="flex flex-col gap-3">
              {executionPlan.tasks.map((task, index) => (
                <li
                  className="flex flex-col gap-2 rounded-ds-md border border-ds-line bg-ds-bg-3 p-4"
                  key={task.task_id}
                >
                  <div className="flex items-start justify-between gap-3">
                    <strong className="text-sm font-semibold text-ds-fg">
                      {index + 1}. {task.title}
                    </strong>
                    <Badge variant="secondary">{task.category}</Badge>
                  </div>
                  <p className="text-sm text-ds-fg-2">{task.description}</p>
                  <p className="text-xs text-ds-fg-3">
                    Source: {task.source_agent} · Status: {task.status}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default ExecutionPlanPanel;
