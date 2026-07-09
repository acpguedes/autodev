/**
 * Typed client for the `/v2/plans` control-plane endpoints (E16-S2 / E17-S2).
 *
 * Mirrors the conventions established in `lib/api_v2.ts` (JSDoc, `schemaVersion`
 * response fields, `requestJson`/`buildUrl` reuse) but lives in its own module so
 * `api_v2.ts` stays under the repository's 500-line-per-file limit.
 *
 * The screen that consumes this client never touches the State Store or other
 * backend internals directly — every read and write goes through these `/v2`
 * endpoints (v2 platform reference §2.13).
 */

import { requestJson } from "./api_ext";

/** Approval-gate state of a single plan step, mirrored from `backend/plans/step_state.py`. */
export type PlanStepState =
  | "draft"
  | "under_review"
  | "approved"
  | "rejected"
  | "executing"
  | "completed";

/** A single plan step and its current approval state. */
export interface PlanStepV2 {
  schemaVersion: string;
  session_id: string;
  step_index: number;
  content: string;
  state: PlanStepState;
  updated_at: string;
}

/** A session's plan, rolled up from its steps' individual states. */
export interface PlanV2 {
  schemaVersion: string;
  session_id: string;
  status: PlanStepState | string;
  steps: PlanStepV2[];
}

/** States in which a step's content may still be edited (`backend/plans/step_state.py::EDITABLE_STATES`). */
export const EDITABLE_STEP_STATES: ReadonlySet<PlanStepState> = new Set(["draft", "under_review"]);

/** States in which a step may be removed (`backend/plans/step_state.py::REMOVABLE_STATES`). */
export const REMOVABLE_STEP_STATES: ReadonlySet<PlanStepState> = new Set([
  "draft",
  "under_review",
  "rejected",
]);

/**
 * Fetch a session's plan, including every step and its approval state.
 *
 * @param sessionId - The owning session id.
 * @returns The session's plan.
 * @throws Error when the request fails.
 */
export async function getPlanV2(sessionId: string): Promise<PlanV2> {
  return requestJson<PlanV2>(`v2/plans/${encodeURIComponent(sessionId)}`);
}

/**
 * Replace a step's content while it is still editable.
 *
 * @param sessionId - The owning session id.
 * @param stepIndex - Zero-based position of the step within the plan.
 * @param content - The step's new content.
 * @returns The updated step.
 * @throws Error when the request fails (for example, the step is no longer editable).
 */
export async function updatePlanStepV2(
  sessionId: string,
  stepIndex: number,
  content: string,
): Promise<PlanStepV2> {
  return requestJson<PlanStepV2>(
    `v2/plans/${encodeURIComponent(sessionId)}/steps/${stepIndex}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );
}

/**
 * Approve a step that is currently under review.
 *
 * @param sessionId - The owning session id.
 * @param stepIndex - Zero-based position of the step within the plan.
 * @param actor - Who is approving the step. Defaults to `"anonymous"`.
 * @param note - Optional note to record alongside the decision.
 * @returns The updated step.
 * @throws Error when the request fails (for example, the step is not under review).
 */
export async function approvePlanStepV2(
  sessionId: string,
  stepIndex: number,
  actor = "anonymous",
  note = "",
): Promise<PlanStepV2> {
  return requestJson<PlanStepV2>(
    `v2/plans/${encodeURIComponent(sessionId)}/steps/${stepIndex}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor, note }),
    },
  );
}

/**
 * Reject a step that is currently under review.
 *
 * @param sessionId - The owning session id.
 * @param stepIndex - Zero-based position of the step within the plan.
 * @param actor - Who is rejecting the step. Defaults to `"anonymous"`.
 * @param note - Optional note to record alongside the decision.
 * @returns The updated step.
 * @throws Error when the request fails (for example, the step is not under review).
 */
export async function rejectPlanStepV2(
  sessionId: string,
  stepIndex: number,
  actor = "anonymous",
  note = "",
): Promise<PlanStepV2> {
  return requestJson<PlanStepV2>(
    `v2/plans/${encodeURIComponent(sessionId)}/steps/${stepIndex}/reject`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor, note }),
    },
  );
}

/**
 * Execute every currently-approved step, or a specific subset of already-approved steps.
 *
 * @param sessionId - The owning session id.
 * @param options - Optional `stepIndices` to execute (all must already be approved) and `actor`.
 * @returns The updated plan.
 * @throws Error when the request fails (for example, no step is approved).
 */
export async function executeApprovedStepsV2(
  sessionId: string,
  options?: { stepIndices?: number[]; actor?: string },
): Promise<PlanV2> {
  return requestJson<PlanV2>(`v2/plans/${encodeURIComponent(sessionId)}/execute-approved`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      step_indices: options?.stepIndices ?? null,
      actor: options?.actor ?? "anonymous",
    }),
  });
}

/**
 * Append a new step to a plan.
 *
 * @param sessionId - The owning session id.
 * @param content - Content for the new step.
 * @param actor - Who is adding the step. Defaults to `"anonymous"`.
 * @returns The updated plan (including the newly added step).
 * @throws Error when the request fails.
 */
export async function addPlanStepV2(
  sessionId: string,
  content: string,
  actor = "anonymous",
): Promise<PlanV2> {
  return requestJson<PlanV2>(`v2/plans/${encodeURIComponent(sessionId)}/steps`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, actor }),
  });
}

/**
 * Remove a step that is not yet approved (or has been rejected).
 *
 * @param sessionId - The owning session id.
 * @param stepIndex - Zero-based position of the step within the plan.
 * @param actor - Who is removing the step. Defaults to `"anonymous"`.
 * @returns The updated plan.
 * @throws Error when the request fails (for example, the step is approved and not removable).
 */
export async function removePlanStepV2(
  sessionId: string,
  stepIndex: number,
  actor = "anonymous",
): Promise<PlanV2> {
  const query = new URLSearchParams({ actor });
  return requestJson<PlanV2>(
    `v2/plans/${encodeURIComponent(sessionId)}/steps/${stepIndex}?${query.toString()}`,
    { method: "DELETE" },
  );
}

/**
 * Split a step's stored `content` into a title and description for editing.
 *
 * The backend only stores a single `content` string per step (there is no
 * dedicated title/description field), so the client convention is to encode
 * the title as the first line and the description as the remainder,
 * separated by a blank line — see {@link joinStepContent}.
 *
 * @param content - The step's raw content string.
 * @returns The derived `{ title, description }` pair.
 */
export function splitStepContent(content: string): { title: string; description: string } {
  const [firstLine, ...rest] = content.split("\n\n");
  return { title: firstLine.trim(), description: rest.join("\n\n").trim() };
}

/**
 * Join a title and description back into the `content` string stored by the backend.
 *
 * Inverse of {@link splitStepContent}.
 *
 * @param title - The step's title (first line of the stored content).
 * @param description - The step's description (remainder of the stored content).
 * @returns The combined content string.
 */
export function joinStepContent(title: string, description: string): string {
  const trimmedTitle = title.trim();
  const trimmedDescription = description.trim();
  return trimmedDescription ? `${trimmedTitle}\n\n${trimmedDescription}` : trimmedTitle;
}
