/**
 * Typed client for the `/v2/execution/*` control-plane endpoints (E14-S3/S5).
 *
 * Mirrors the conventions established in `lib/plans_v2.ts` (JSDoc,
 * `schemaVersion` response fields, `requestJson` reuse). The screen that
 * consumes this client never touches the State Store or other backend
 * internals directly — every read and write goes through these `/v2`
 * endpoints (v2 platform reference §2.13).
 */

import { requestJson } from "./api_ext";

/** Execution mode governing whether a task's actions run automatically,
 * always pause for a human decision, or pause only when policy doesn't
 * cover them (`backend/execution/modes.py::ExecutionMode`). */
export type ExecutionModeV2 = "auto" | "approval" | "hybrid";

/** One pending execution-action decision (`backend/execution/policy.py::PendingDecision`). */
export interface PendingDecisionV2 {
  decisionId: string;
  runId: string;
  taskId: string;
  category: string;
  prompt: string;
  status: "pending" | "approved" | "denied" | "timed_out";
  createdAt: string;
  expiresAt: string;
}

/** One hybrid-mode "always" grant (`backend/execution/policy.py::PolicyRule`). */
export interface DynamicPermissionV2 {
  permissionId: string;
  category: string;
  scopeKind: string;
  scopeId: string;
  pattern: string | null;
}

/**
 * List the caller's own tenant's still-pending execution-action decisions.
 *
 * @returns The pending decisions.
 * @throws Error when the request fails.
 */
export async function listPendingDecisionsV2(): Promise<PendingDecisionV2[]> {
  const response = await requestJson<{ decisions: PendingDecisionV2[] }>("v2/execution/decisions");
  return response.decisions;
}

/**
 * Approve or deny a pending execution-action decision.
 *
 * @param decisionId - The decision to resolve.
 * @param decision - `"approve"` or `"deny"`.
 * @param persistAsRule - Hybrid mode's "always" option: also grant a durable
 *   dynamic permission so equivalent future actions auto-allow.
 * @returns The resolved decision.
 * @throws Error when the request fails (for example, already resolved).
 */
export async function resolveDecisionV2(
  decisionId: string,
  decision: "approve" | "deny",
  persistAsRule = false,
): Promise<PendingDecisionV2> {
  return requestJson<PendingDecisionV2>(
    `v2/execution/decisions/${encodeURIComponent(decisionId)}/resolve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, persistAsRule }),
    },
  );
}

/**
 * List the caller's own tenant's currently granted dynamic permissions.
 *
 * @returns The granted permissions.
 * @throws Error when the request fails.
 */
export async function listDynamicPermissionsV2(): Promise<DynamicPermissionV2[]> {
  const response = await requestJson<{ permissions: DynamicPermissionV2[] }>(
    "v2/execution/policy/dynamic",
  );
  return response.permissions;
}

/**
 * Revoke a previously granted dynamic permission.
 *
 * @param permissionId - The permission to revoke.
 * @throws Error when the request fails (for example, already revoked).
 */
export async function revokeDynamicPermissionV2(permissionId: string): Promise<void> {
  await requestJson<void>(`v2/execution/policy/dynamic/${encodeURIComponent(permissionId)}`, {
    method: "DELETE",
  });
}

/**
 * Resume a plan-execution run paused awaiting a human decision.
 *
 * @param sessionId - The owning session id.
 * @param runId - The paused run to resume.
 * @param mode - Execution mode for the resumed portion; pass the same mode
 *   the run started with.
 * @returns The run's status after resuming (`"completed"` or
 *   `"awaiting_approval"` again, at the next task needing a decision).
 * @throws Error when the request fails.
 */
export async function resumeExecutionPlanV2(
  sessionId: string,
  runId: string,
  mode: ExecutionModeV2 = "auto",
): Promise<{ run_id: string; status: string }> {
  const query = new URLSearchParams({ run_id: runId, mode });
  return requestJson<{ run_id: string; status: string }>(
    `v2/sessions/${encodeURIComponent(sessionId)}/execution-plan/resume?${query.toString()}`,
    { method: "POST" },
  );
}
