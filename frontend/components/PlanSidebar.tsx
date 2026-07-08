"use client";

import { Card, CardContent, CardHeader } from "@/components/ui/card";

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
    <div className="grid gap-4 md:grid-cols-2">
      <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
        <CardHeader className="pb-3">
          <h2 className="font-serif text-base font-semibold text-ds-fg">Execution plan</h2>
        </CardHeader>
        <CardContent>
          <ol className="list-decimal pl-5 text-sm text-ds-fg-2 marker:text-ds-fg-3">
            {plan.map((step, index) => (
              <li className="mb-1.5 last:mb-0" key={index}>
                {step}
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
        <CardHeader className="pb-3">
          <h2 className="font-serif text-base font-semibold text-ds-fg">Workspace</h2>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">
                Label
              </dt>
              <dd className="text-sm text-ds-fg">{repositoryLabel || "Not configured"}</dd>
            </div>
            <div>
              <dt className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">
                Session
              </dt>
              <dd className="break-all text-sm text-ds-fg">{sessionId || "No session yet"}</dd>
            </div>
            <div>
              <dt className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">
                Status
              </dt>
              <dd className="text-sm text-ds-fg">{status || "idle"}</dd>
            </div>
            <div>
              <dt className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">
                Root
              </dt>
              <dd className="break-all text-sm text-ds-fg">{projectRoot || "Not configured"}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

export default PlanSidebar;
