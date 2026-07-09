"use client";

import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { useTranslations } from "@/lib/i18n";
import {
  EDITABLE_STEP_STATES,
  REMOVABLE_STEP_STATES,
  joinStepContent,
  splitStepContent,
  type PlanStepV2,
} from "@/lib/plans_v2";

import { StepStatusBadge } from "./StepStatusBadge";

const fieldClass =
  "w-full rounded-ds-md border border-ds-line bg-ds-bg px-2 py-1 text-sm text-ds-fg shadow-sm placeholder:text-ds-fg-3 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ds-accent";

function cardToneClass(state: PlanStepV2["state"]): string {
  if (state === "rejected") {
    return "border-ds-line bg-ds-bg-2 opacity-60 shadow-ds-sm";
  }
  if (state === "approved" || state === "executing" || state === "completed") {
    return "border-ds-accent/50 bg-ds-bg-2 shadow-ds-sm";
  }
  return "border-ds-line bg-ds-bg-2 shadow-ds-sm";
}

export interface StepCardProps {
  /** 1-based display position of this step within the plan. */
  index: number;
  /** The step to render. */
  step: PlanStepV2;
  /** Disables every action while a request for this step is in flight. */
  busy: boolean;
  /** Persists edited content for this step. Resolves to whether the save succeeded. */
  onSave: (content: string) => Promise<boolean>;
  /** Approves the step. Only rendered while the step is under review. */
  onApprove: () => void;
  /** Rejects the step. Only rendered while the step is under review. */
  onReject: () => void;
  /** Removes the step. Only rendered while the step is removable. */
  onRemove: () => void;
}

/**
 * A single plan step: numbered header, status pill, inline title/description
 * editing gated on the step's approval state, and approve/reject/remove
 * actions gated on the same state machine enforced server-side by
 * `backend/plans/step_state.py`.
 */
export function StepCard({ index, step, busy, onSave, onApprove, onReject, onRemove }: StepCardProps) {
  const { t } = useTranslations();
  const titleId = useId();
  const descriptionId = useId();
  const { title: savedTitle, description: savedDescription } = splitStepContent(step.content);

  const [isEditing, setIsEditing] = useState(false);
  const [title, setTitle] = useState(savedTitle);
  const [description, setDescription] = useState(savedDescription);

  const editable = EDITABLE_STEP_STATES.has(step.state);
  const removable = REMOVABLE_STEP_STATES.has(step.state);
  const pendingDecision = step.state === "under_review";

  function startEditing() {
    setTitle(savedTitle);
    setDescription(savedDescription);
    setIsEditing(true);
  }

  function handleCancel() {
    setIsEditing(false);
  }

  async function handleSave() {
    const succeeded = await onSave(joinStepContent(title, description));
    if (succeeded) {
      setIsEditing(false);
    }
  }

  return (
    <div className={`rounded-ds-md border p-4 ${cardToneClass(step.state)}`}>
      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-1 items-start gap-3">
            <span
              aria-hidden="true"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ds-accent/15 text-xs font-semibold text-ds-accent"
            >
              {index}
            </span>
            {isEditing ? (
              <div className="flex flex-1 flex-col gap-1">
                <label htmlFor={titleId} className="sr-only">
                  {t("plans.step.titlePlaceholder")}
                </label>
                <input
                  id={titleId}
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder={t("plans.step.titlePlaceholder")}
                  className={`${fieldClass} font-semibold`}
                />
              </div>
            ) : (
              <p className="pt-0.5 text-sm font-semibold text-ds-fg">{savedTitle}</p>
            )}
          </div>
          <StepStatusBadge state={step.state} label={t(`plans.status.${step.state}`)} />
        </div>

        {isEditing ? (
          <div className="flex flex-col gap-1">
            <label htmlFor={descriptionId} className="sr-only">
              {t("plans.step.descriptionPlaceholder")}
            </label>
            <textarea
              id={descriptionId}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t("plans.step.descriptionPlaceholder")}
              className={`${fieldClass} min-h-[80px] resize-y`}
            />
          </div>
        ) : (
          savedDescription && <p className="text-sm text-ds-fg-3">{savedDescription}</p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {isEditing ? (
            <>
              <Button size="sm" onClick={handleSave} disabled={busy}>
                {t("plans.step.save")}
              </Button>
              <Button size="sm" variant="outline" onClick={handleCancel} disabled={busy}>
                {t("plans.step.cancel")}
              </Button>
            </>
          ) : (
            <>
              {pendingDecision && (
                <>
                  <Button size="sm" onClick={onApprove} disabled={busy}>
                    {t("plans.step.approve")}
                  </Button>
                  <Button size="sm" variant="outline" onClick={onReject} disabled={busy}>
                    {t("plans.step.reject")}
                  </Button>
                </>
              )}
              {editable && (
                <Button size="sm" variant="ghost" onClick={startEditing} disabled={busy}>
                  {t("plans.step.edit")}
                </Button>
              )}
            </>
          )}
          {removable && !isEditing && (
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="ml-auto text-ds-fg-3 hover:text-ds-danger"
              onClick={onRemove}
              disabled={busy}
              aria-label={t("plans.step.removeLabel", { index })}
            >
              <span aria-hidden="true">&times;</span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
