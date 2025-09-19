"use client";

type PlanSidebarProps = {
  plan: string[];
};

export function PlanSidebar({ plan }: PlanSidebarProps) {
  return (
    <div>
      <h2 className="sidebar-title">Execution plan</h2>
      <ol className="sidebar-plan">
        {plan.map((step, index) => (
          <li key={index}>{step}</li>
        ))}
      </ol>
    </div>
  );
}

export default PlanSidebar;
