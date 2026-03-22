"use client";

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
    <section className="panel-card">
      <div className="panel-card__header panel-card__header--stack-mobile">
        <div>
          <p className="eyebrow">Post-analysis workflow</p>
          <h2>Step-by-step execution plan</h2>
          <p className="subtitle">
            Convert the latest analysis into an ordered task list and execute each task sequentially.
          </p>
        </div>

        <button
          className="secondary-button"
          type="button"
          onClick={() => void onExecute()}
          disabled={!executionPlan || executionPlan.tasks.length === 0 || isExecuting}
        >
          {isExecuting ? "Executing plan..." : "Execute plan"}
        </button>
      </div>

      {!executionPlan ? (
        <p className="empty-state">Loading execution plan...</p>
      ) : executionPlan.tasks.length === 0 ? (
        <div className="instruction-stack">
          <p className="status-text">{executionPlan.summary}</p>
          <p className="empty-state">
            Send a message to the agents first so the analyzer can produce the execution backlog.
          </p>
        </div>
      ) : (
        <div className="execution-plan">
          <div className="execution-plan__summary">
            <p className="info-label">Analysis summary</p>
            <p>{executionPlan.analysis_summary}</p>
            <p className="status-text">{executionPlan.summary}</p>
          </div>

          <ol className="execution-task-list">
            {executionPlan.tasks.map((task, index) => (
              <li className="execution-task-card" key={task.task_id}>
                <div className="execution-task-card__header">
                  <strong>
                    {index + 1}. {task.title}
                  </strong>
                  <span className="status-pill">{task.category}</span>
                </div>
                <p>{task.description}</p>
                <p className="run-card__meta">
                  Source: {task.source_agent} · Status: {task.status}
                </p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

export default ExecutionPlanPanel;
