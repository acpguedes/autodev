"use client";

import { RunResponse } from "../lib/api";

type RunHistoryPanelProps = {
  runs: RunResponse[];
};

export function RunHistoryPanel({ runs }: RunHistoryPanelProps) {
  return (
    <section className="panel-card">
      <div className="panel-card__header">
        <div>
          <p className="eyebrow">Run timeline</p>
          <h2>Recent executions</h2>
        </div>
      </div>

      {runs.length === 0 ? (
        <p className="empty-state">No runs yet for the current session.</p>
      ) : (
        <div className="run-list">
          {runs.map((run) => (
            <article className="run-card" key={run.run_id}>
              <div className="run-card__summary">
                <div>
                  <strong>{run.run_type}</strong>
                  <p>{run.trigger_message}</p>
                </div>
                <span className="status-pill">{run.status}</span>
              </div>
              <p className="run-card__meta">
                State: {run.current_state} · Steps: {run.steps.length} · Created: {run.created_at}
              </p>
              <ol className="run-steps">
                {run.steps.map((step) => (
                  <li key={`${run.run_id}-${step.step_key}`}>
                    <span>{step.agent}</span>
                    <span>{step.status}</span>
                  </li>
                ))}
              </ol>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export default RunHistoryPanel;
