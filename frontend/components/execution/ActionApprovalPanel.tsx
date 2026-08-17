"use client";

import { Button } from "@/components/ui/button";
import { useTranslations } from "@/lib/i18n";
import type { PendingDecisionV2 } from "@/lib/execution_v2";

import { DecisionCategoryBadge } from "./DecisionCategoryBadge";

export interface ActionApprovalPanelProps {
  /** The pending decision to render. */
  decision: PendingDecisionV2;
  /** Disables every action while a request for this decision is in flight. */
  busy: boolean;
  /** Approves the decision, running its action once. */
  onApproveOnce: () => void;
  /** Approves the decision and persists a dynamic permission for equivalent future actions (hybrid mode's "always" option). */
  onApproveAlways: () => void;
  /** Denies the decision; the task fails and execution continues past it. */
  onDeny: () => void;
}

/**
 * One pending execution-action decision (E14-S5): category badge, the
 * human-readable prompt, and the approve-once / approve-always / deny
 * actions backing `POST /v2/execution/decisions/{id}/resolve`.
 */
export function ActionApprovalPanel({
  decision,
  busy,
  onApproveOnce,
  onApproveAlways,
  onDeny,
}: ActionApprovalPanelProps) {
  const { t } = useTranslations();

  return (
    <div className="flex flex-col gap-3 rounded-ds-md border border-ds-line bg-ds-bg-2 p-4 shadow-ds-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="text-sm font-semibold text-ds-fg">{decision.prompt}</p>
          <p className="text-xs text-ds-fg-2">
            {t("execution.decision.task", { taskId: decision.taskId })}
          </p>
        </div>
        <DecisionCategoryBadge category={decision.category} />
      </div>
      <p className="text-xs text-ds-fg-2">
        {t("execution.decision.expiresAt", { expiresAt: decision.expiresAt })}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={onApproveOnce} disabled={busy}>
          {t("execution.decision.approve")}
        </Button>
        <Button size="sm" variant="outline" onClick={onApproveAlways} disabled={busy}>
          {t("execution.decision.approveAlways")}
        </Button>
        <Button size="sm" variant="ghost" className="text-ds-danger" onClick={onDeny} disabled={busy}>
          {t("execution.decision.deny")}
        </Button>
      </div>
    </div>
  );
}
