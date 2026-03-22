"use client";

type PlanSidebarProps = {
  plan: string[];
  sessionId?: string | null;
  status?: string | null;
  repositoryLabel?: string;
  projectRoot?: string;
};

export function PlanSidebar({
  plan,
  sessionId,
  status,
  repositoryLabel,
  projectRoot,
}: PlanSidebarProps) {
  return (
    <div className="sidebar-stack">
      <section className="sidebar-card">
        <h2 className="sidebar-title">Execution plan</h2>
        <ol className="sidebar-plan">
          {plan.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
      </section>

      <section className="sidebar-card sidebar-card--compact">
        <h2 className="sidebar-title">Workspace</h2>
        <dl className="sidebar-metadata">
          <div>
            <dt>Label</dt>
            <dd>{repositoryLabel || "Not configured"}</dd>
          </div>
          <div>
            <dt>Session</dt>
            <dd>{sessionId || "No session yet"}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{status || "idle"}</dd>
          </div>
          <div>
            <dt>Root</dt>
            <dd>{projectRoot || "Not configured"}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

export default PlanSidebar;
