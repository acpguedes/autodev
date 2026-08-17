# Web UX for Governed Execution (E14-S5)

> Story definition: `docs/v2_platform/phases/e14_real_execution_governance.md#e14-s5`.

## Screen

`/execution` (`frontend/app/execution/page.tsx`), added to the primary nav
rail (`frontend/components/shell/navModel.ts`). Wired exclusively to
`/v2/execution/*` (`frontend/lib/execution_v2.ts`) plus the E9-S2 SSE
run-events stream — never the State Store or other backend internals
directly.

Three sections:

1. **Pending decisions** (`ActionApprovalPanel`) — every decision for the
   caller's tenant (E14-S3's `GET /v2/execution/decisions` is tenant-scoped,
   not session-scoped, so unlike the Plans screen there is no session
   lookup step). Approve once, approve always (hybrid's "always" option —
   persists a dynamic permission), or deny.
2. **Dynamic permissions** (`DynamicPermissionsList`) — every grant made by
   an "approve always" resolution, with a revoke button
   (`DELETE /v2/execution/policy/dynamic/{id}`).
3. **Execution log** (`ExecutionActionLog`) — real-time
   `execution.action.*` events for an operator-entered run id, plus a
   "resume" control once a session id is also supplied
   (`POST /v2/sessions/{id}/execution-plan/resume`).

## Real-time log: a new stream, not `lib/timeline.ts`

The plan for this story said to extend `lib/timeline.ts`'s
`applyTimelineEvent`. Reading the actual module changed that: it folds
events into four **fixed** stages (`planning`/`analysis`/`patch`/
`validation`) from a `RunTimelineStepData` payload
(`{stepKey, actorRole, status, output}`). `execution.action.*` events have
a different payload (`{actionId, taskId, type}` / `{..., status, exitCode}`
/ `{..., error}`) and don't correspond to one of those four stages — trying
to force them through `applyTimelineEvent` would have been a type-shape
mismatch, not a real extension.

Instead, `frontend/lib/execution_events.ts` is a small, parallel module:
the same E9-S2 transport primitives (`runEventsStreamUrl`, `parseSseBuffer`,
the `fetch` + incremental-decode loop `useRunTimeline` already
established) but its own `parseExecutionActionEvent` and a flat
`useExecutionActionLog(runId)` hook — a scrolling list of events, not a
4-stage progress bar. The SSE transport itself needed **zero** server-side
changes either way, confirming the research: any event already in
`EVENT_CATALOG` reaches the frontend through the existing endpoint; only
the UI-side parsing is per-type.

## Scope reductions (stated, not hidden)

- **No pre-approval diff preview.** A `PendingDecision` carries `category`/
  `prompt`/`pattern`, not the prospective file diff — the backend doesn't
  compute one before an action runs (it's paused *before* dispatch, by
  definition). The panel shows the prompt and pattern; the actual diff/log
  appears in the execution log once the action has run. Computing a
  pre-approval diff preview is a backend capability this story didn't add.
- **No cancel button.** E14-S3 shipped `execute`/`resume`, not a `cancel`
  endpoint. The plan mentioned a `POST .../execution-plan/cancel` as a
  possibility; building it wasn't warranted mid-frontend-story scope for a
  button with nothing to call — pause/resume is fully wired, cancel is not.
- **Coverage matches the existing per-screen bar**, not a broader audit:
  one Storybook story file per new component (automatic axe a11y, same as
  `StepCard`) and one Playwright e2e spec
  (`e2e/execution-approval.spec.ts`) covering approve-clears-the-list and
  the live log — not a full accessibility/interaction matrix.
