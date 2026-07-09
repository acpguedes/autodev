"use client";

import { FormEvent, useCallback, useMemo, useState } from "react";

import { ExecuteApprovedFooter } from "@/components/plans/ExecuteApprovedFooter";
import { StatCard } from "@/components/plans/StatCard";
import { StepCard } from "@/components/plans/StepCard";
import { useShellHeader } from "@/components/shell/ShellProvider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTranslations } from "@/lib/i18n";
import {
  addPlanStepV2,
  approvePlanStepV2,
  executeApprovedStepsV2,
  getPlanV2,
  rejectPlanStepV2,
  removePlanStepV2,
  updatePlanStepV2,
  type PlanStepV2,
  type PlanV2,
} from "@/lib/plans_v2";

/**
 * Replace a single step within a plan by matching `step_index`, leaving
 * every other step untouched.
 *
 * @param plan - The plan to update.
 * @param updated - The step's new value.
 * @returns A new plan with `updated` merged in.
 */
function mergeStep(plan: PlanV2, updated: PlanStepV2): PlanV2 {
  return {
    ...plan,
    steps: plan.steps.map((existing) => (existing.step_index === updated.step_index ? updated : existing)),
  };
}

/** Approval Control Center "Plans" screen (E17-S2): stat cards, editable step cards with
 * approve/reject gates, add/remove step, and a sticky "execute approved plan" footer —
 * wired exclusively to the `/v2/plans` endpoints (E16-S2).
 */
export default function PlansPage() {
  const { t } = useTranslations();

  useShellHeader({
    title: t("plans.pageTitle"),
    subtitle: t("plans.pageSubtitle"),
  });

  const [sessionIdInput, setSessionIdInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [plan, setPlan] = useState<PlanV2 | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stepBusy, setStepBusy] = useState<Record<number, boolean>>({});
  const [addingStep, setAddingStep] = useState(false);
  const [executingApproved, setExecutingApproved] = useState(false);

  const setBusy = useCallback((stepIndex: number, busy: boolean) => {
    setStepBusy((current) => ({ ...current, [stepIndex]: busy }));
  }, []);

  /** Drops a step's `stepBusy` entry entirely, instead of leaving a stale
   * `true` flag behind once the step itself has been removed from the plan. */
  const clearBusy = useCallback((stepIndex: number) => {
    setStepBusy((current) => {
      const { [stepIndex]: _removed, ...rest } = current;
      return rest;
    });
  }, []);

  const loadPlan = useCallback(
    async (targetSessionId: string) => {
      setLoading(true);
      setError(null);
      try {
        const loaded = await getPlanV2(targetSessionId);
        setPlan(loaded);
        setSessionId(targetSessionId);
      } catch {
        setError(t("plans.errors.loadPlan"));
        setPlan(null);
      } finally {
        setLoading(false);
      }
    },
    [t],
  );

  async function handleLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sessionIdInput.trim()) {
      await loadPlan(sessionIdInput.trim());
    }
  }

  const handleSaveStep = useCallback(
    async (stepIndex: number, content: string): Promise<boolean> => {
      if (!sessionId) {
        return false;
      }
      setBusy(stepIndex, true);
      setError(null);
      try {
        const updated = await updatePlanStepV2(sessionId, stepIndex, content);
        setPlan((current) => (current ? mergeStep(current, updated) : current));
        return true;
      } catch {
        setError(t("plans.errors.updateStep"));
        return false;
      } finally {
        setBusy(stepIndex, false);
      }
    },
    [sessionId, setBusy, t],
  );

  const handleApprove = useCallback(
    async (stepIndex: number) => {
      if (!sessionId) {
        return;
      }
      setBusy(stepIndex, true);
      setError(null);
      try {
        const updated = await approvePlanStepV2(sessionId, stepIndex);
        setPlan((current) => (current ? mergeStep(current, updated) : current));
      } catch {
        setError(t("plans.errors.approveStep"));
      } finally {
        setBusy(stepIndex, false);
      }
    },
    [sessionId, setBusy, t],
  );

  const handleReject = useCallback(
    async (stepIndex: number) => {
      if (!sessionId) {
        return;
      }
      setBusy(stepIndex, true);
      setError(null);
      try {
        const updated = await rejectPlanStepV2(sessionId, stepIndex);
        setPlan((current) => (current ? mergeStep(current, updated) : current));
      } catch {
        setError(t("plans.errors.rejectStep"));
      } finally {
        setBusy(stepIndex, false);
      }
    },
    [sessionId, setBusy, t],
  );

  const handleRemove = useCallback(
    async (stepIndex: number) => {
      if (!sessionId) {
        return;
      }
      setBusy(stepIndex, true);
      setError(null);
      try {
        const updatedPlan = await removePlanStepV2(sessionId, stepIndex);
        setPlan(updatedPlan);
        clearBusy(stepIndex);
      } catch {
        setError(t("plans.errors.removeStep"));
        setBusy(stepIndex, false);
      }
    },
    [sessionId, setBusy, clearBusy, t],
  );

  const handleAddStep = useCallback(async () => {
    if (!sessionId) {
      return;
    }
    setAddingStep(true);
    setError(null);
    try {
      const updatedPlan = await addPlanStepV2(sessionId, t("plans.step.defaultTitle"));
      setPlan(updatedPlan);
    } catch {
      setError(t("plans.errors.addStep"));
    } finally {
      setAddingStep(false);
    }
  }, [sessionId, t]);

  const handleExecuteApproved = useCallback(async () => {
    if (!sessionId) {
      return;
    }
    setExecutingApproved(true);
    setError(null);
    try {
      const updatedPlan = await executeApprovedStepsV2(sessionId);
      setPlan(updatedPlan);
    } catch {
      setError(t("plans.errors.executePlan"));
    } finally {
      setExecutingApproved(false);
    }
  }, [sessionId, t]);

  const approvedCount = useMemo(
    () => (plan ? plan.steps.filter((step) => step.state === "approved").length : 0),
    [plan],
  );
  const pendingCount = useMemo(
    () => (plan ? plan.steps.filter((step) => step.state === "draft" || step.state === "under_review").length : 0),
    [plan],
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-8">
        <header className="flex flex-col gap-2">
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-2">
            {t("plans.pageTitle")}
          </p>
          <h2 className="font-serif text-2xl font-semibold text-ds-fg">{t("plans.pageSubtitle")}</h2>
        </header>

        <form className="flex flex-col gap-3 sm:flex-row" onSubmit={handleLookup}>
          <Input
            value={sessionIdInput}
            onChange={(event) => setSessionIdInput(event.target.value)}
            placeholder={t("plans.sessionPlaceholder")}
            aria-label={t("plans.sessionLabel")}
          />
          <Button type="submit" disabled={loading || !sessionIdInput.trim()}>
            {loading ? t("plans.loading") : t("plans.load")}
          </Button>
        </form>

        {error && (
          <p role="alert" className="rounded-ds-md border border-ds-danger/40 bg-ds-danger/10 px-3 py-2 text-sm text-ds-danger">
            {error}
          </p>
        )}

        {!plan ? (
          <p className="text-sm text-ds-fg-2">{t("plans.empty")}</p>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <StatCard label={t("plans.stats.steps")} value={plan.steps.length} />
              <StatCard label={t("plans.stats.approved")} value={approvedCount} />
              <StatCard label={t("plans.stats.pending")} value={pendingCount} />
            </div>

            <div className="flex flex-col gap-3">
              {plan.steps.length === 0 ? (
                <p className="text-sm text-ds-fg-2">{t("plans.emptySteps")}</p>
              ) : (
                plan.steps.map((step, position) => (
                  <StepCard
                    key={step.step_index}
                    index={position + 1}
                    step={step}
                    busy={Boolean(stepBusy[step.step_index])}
                    onSave={(content) => handleSaveStep(step.step_index, content)}
                    onApprove={() => handleApprove(step.step_index)}
                    onReject={() => handleReject(step.step_index)}
                    onRemove={() => handleRemove(step.step_index)}
                  />
                ))
              )}

              <button
                type="button"
                onClick={handleAddStep}
                disabled={addingStep}
                className="rounded-ds-md border border-dashed border-ds-line px-4 py-3 text-sm font-medium text-ds-fg-2 transition-colors hover:border-ds-accent hover:text-ds-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ds-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {addingStep ? t("plans.addingStep") : `+ ${t("plans.addStep")}`}
              </button>
            </div>
          </>
        )}
      </div>

      {plan && (
        <ExecuteApprovedFooter
          approvedCount={approvedCount}
          executing={executingApproved}
          onExecute={handleExecuteApproved}
          label={t("plans.executeApproved")}
          executingLabel={t("plans.executingApproved")}
          needsApprovalLabel={t("plans.needsApproval")}
        />
      )}
    </div>
  );
}
