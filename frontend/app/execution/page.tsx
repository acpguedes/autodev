"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { ActionApprovalPanel } from "@/components/execution/ActionApprovalPanel";
import { DynamicPermissionsList } from "@/components/execution/DynamicPermissionsList";
import { ExecutionActionLog } from "@/components/execution/ExecutionActionLog";
import { useShellHeader } from "@/components/shell/ShellProvider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTranslations } from "@/lib/i18n";
import {
  listDynamicPermissionsV2,
  listPendingDecisionsV2,
  resolveDecisionV2,
  resumeExecutionPlanV2,
  revokeDynamicPermissionV2,
  type DynamicPermissionV2,
  type PendingDecisionV2,
} from "@/lib/execution_v2";

/**
 * Execution Control Center "Execution" screen (E14-S5): pending
 * approval/hybrid-mode decisions, granted dynamic permissions, and a
 * real-time execution log — wired exclusively to the `/v2/execution/*`
 * endpoints (E14-S3).
 *
 * Scope note: unlike the Plans screen, decisions/permissions are listed
 * for the caller's whole tenant (the backend has no session-scoped
 * listing), so this screen has no session lookup step. Resuming a paused
 * run still needs its `sessionId` — captured from the decision's own
 * `runId` is not enough since the backend's resume endpoint is
 * session-scoped; the operator supplies it alongside the run id.
 */
export default function ExecutionPage() {
  const { t } = useTranslations();

  useShellHeader({
    title: t("execution.pageTitle"),
    subtitle: t("execution.pageSubtitle"),
  });

  const [decisions, setDecisions] = useState<PendingDecisionV2[]>([]);
  const [permissions, setPermissions] = useState<DynamicPermissionV2[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decisionBusy, setDecisionBusy] = useState<Record<string, boolean>>({});
  const [permissionBusy, setPermissionBusy] = useState<Set<string>>(new Set());

  const [watchedRunId, setWatchedRunId] = useState<string | null>(null);
  const [runIdInput, setRunIdInput] = useState("");
  const [sessionIdInput, setSessionIdInput] = useState("");
  const [resuming, setResuming] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [loadedDecisions, loadedPermissions] = await Promise.all([
        listPendingDecisionsV2(),
        listDynamicPermissionsV2(),
      ]);
      setDecisions(loadedDecisions);
      setPermissions(loadedPermissions);
    } catch {
      setError(t("execution.errors.loadDecisions"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const setBusy = useCallback((decisionId: string, busy: boolean) => {
    setDecisionBusy((current) => ({ ...current, [decisionId]: busy }));
  }, []);

  const handleResolve = useCallback(
    async (decisionId: string, decision: "approve" | "deny", persistAsRule: boolean) => {
      setBusy(decisionId, true);
      setError(null);
      try {
        await resolveDecisionV2(decisionId, decision, persistAsRule);
        setDecisions((current) => current.filter((entry) => entry.decisionId !== decisionId));
        if (persistAsRule) {
          setPermissions(await listDynamicPermissionsV2());
        }
      } catch {
        setError(t("execution.errors.resolveDecision"));
      } finally {
        setBusy(decisionId, false);
      }
    },
    [setBusy, t],
  );

  const handleRevoke = useCallback(
    async (permissionId: string) => {
      setPermissionBusy((current) => new Set(current).add(permissionId));
      setError(null);
      try {
        await revokeDynamicPermissionV2(permissionId);
        setPermissions((current) => current.filter((entry) => entry.permissionId !== permissionId));
      } catch {
        setError(t("execution.errors.revokePermission"));
      } finally {
        setPermissionBusy((current) => {
          const next = new Set(current);
          next.delete(permissionId);
          return next;
        });
      }
    },
    [t],
  );

  function handleWatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (runIdInput.trim()) {
      setWatchedRunId(runIdInput.trim());
    }
  }

  const handleResume = useCallback(async () => {
    if (!sessionIdInput.trim() || !watchedRunId) {
      return;
    }
    setResuming(true);
    setError(null);
    try {
      await resumeExecutionPlanV2(sessionIdInput.trim(), watchedRunId);
      await load();
    } catch {
      setError(t("execution.errors.resume"));
    } finally {
      setResuming(false);
    }
  }, [sessionIdInput, watchedRunId, load, t]);

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto p-8">
      <header className="flex flex-col gap-2">
        <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-2">
          {t("execution.pageTitle")}
        </p>
        <h2 className="font-serif text-2xl font-semibold text-ds-fg">{t("execution.pageSubtitle")}</h2>
      </header>

      {error && (
        <p role="alert" className="rounded-ds-md border border-ds-danger/40 bg-ds-danger/10 px-3 py-2 text-sm text-ds-danger">
          {error}
        </p>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ds-fg">{t("execution.decisionsHeading")}</h3>
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
            {loading ? t("execution.loading") : t("execution.refresh")}
          </Button>
        </div>
        {decisions.length === 0 ? (
          <p className="text-sm text-ds-fg-2">{t("execution.emptyDecisions")}</p>
        ) : (
          <div className="flex flex-col gap-3">
            {decisions.map((decision) => (
              <ActionApprovalPanel
                key={decision.decisionId}
                decision={decision}
                busy={Boolean(decisionBusy[decision.decisionId])}
                onApproveOnce={() => void handleResolve(decision.decisionId, "approve", false)}
                onApproveAlways={() => void handleResolve(decision.decisionId, "approve", true)}
                onDeny={() => void handleResolve(decision.decisionId, "deny", false)}
              />
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-ds-fg">{t("execution.permissionsHeading")}</h3>
        <DynamicPermissionsList permissions={permissions} busyIds={permissionBusy} onRevoke={handleRevoke} />
      </section>

      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-ds-fg">{t("execution.logHeading")}</h3>
        <form className="flex flex-col gap-3 sm:flex-row" onSubmit={handleWatch}>
          <Input
            value={runIdInput}
            onChange={(event) => setRunIdInput(event.target.value)}
            placeholder={t("execution.runIdPlaceholder")}
            aria-label={t("execution.runIdLabel")}
          />
          <Button type="submit" disabled={!runIdInput.trim()}>
            {t("execution.watch")}
          </Button>
        </form>
        <ExecutionActionLog runId={watchedRunId} />
        {watchedRunId && (
          <form
            className="flex flex-col gap-3 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              void handleResume();
            }}
          >
            <Input
              value={sessionIdInput}
              onChange={(event) => setSessionIdInput(event.target.value)}
              placeholder={t("plans.sessionPlaceholder")}
              aria-label={t("plans.sessionLabel")}
            />
            <Button type="submit" variant="outline" disabled={resuming || !sessionIdInput.trim()}>
              {resuming ? t("execution.resuming") : t("execution.resume")}
            </Button>
          </form>
        )}
      </section>
    </div>
  );
}
