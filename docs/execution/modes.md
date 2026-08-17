# Execution Modes: Approval, Auto, Hybrid (E14-S3)

> Story definition: `docs/v2_platform/phases/e14_real_execution_governance.md#e14-s3`.

## Modes

`ExecutionMode` (`backend/execution/modes.py`), passed to
`OrchestratorService.execute_plan(session_id, *, mode=...)`:

- **`auto`** (default — preserves E14-S1/S2 behavior exactly): the E14-S2
  policy engine alone decides; no human is ever involved.
- **`approval`**: every task with at least one derived action pauses for a
  human decision before it runs, regardless of policy.
- **`hybrid`**: a task's actions run automatically when policy covers them
  (`PolicyDecision.matched=True`, allow or deny); when uncovered
  (`matched=False`), the task pauses and offers a 3-option decision.

## Pause / resume

A task requiring a decision does **not** block the API request. Instead:

1. A `PendingDecision` is durably created (`pending_action_decisions` table,
   the same store as E14-S2's policy tables).
2. That task's `RunStep` is marked `awaiting_approval`; the run's overall
   `status` becomes `awaiting_approval`.
3. **Execution stops** — no further tasks in the plan are processed this
   call. Everything completed so far is durably persisted (strengthens
   E14-S1's "interrupted execution preserves partial state" criterion).
4. `POST /v2/execution/decisions/{id}/resolve` (`approve`/`deny`, optional
   `persistAsRule` for hybrid's "always") resolves it.
5. `POST /v2/sessions/{id}/execution-plan/resume?runId=...` continues: it
   re-derives the plan (deterministic given unchanged session artifacts)
   and skips every task with a terminal (`completed`/`failed`) step,
   picking back up from the first non-terminal one.

`mode` is a **per-call parameter, not persisted run state** — callers pass
the same mode again on resume. A future story could persist it if
cross-session resume needs to remember it; not needed for this story's
scope.

## The 3-option hybrid decision

`POST .../resolve` with `decision: "approve"`:

- **Run once**: `persistAsRule: false` (default) — this task's action runs;
  the next uncovered action of the same category still pauses.
- **Always**: `persistAsRule: true` — additionally grants a durable dynamic
  permission (`PolicyRule` with the decision's `category`/`pattern`,
  `effect=allow`) via `PolicyService.grant_dynamic_permission`. Future
  actions matching that category+pattern policy-`evaluate` as allowed
  without pausing again.
- **Deny**: `decision: "deny"` — this task fails; execution continues to
  the next task (a deny does **not** stop the run, unlike a still-pending
  decision).

## Timeout

Every pending decision has a deadline (`AUTODEV_EXECUTION_DECISION_TIMEOUT_SECONDS`,
default 3600s). Reading a decision past its deadline self-expires it to
`timed_out` (`DecisionService._maybe_expire`, checked wherever a decision
is read — no cron dependency for correctness, though
`DecisionService.expire_due()` is also exposed as a standalone sweep for an
operator/cron surface, mirroring `backend.flows.human.FlowHumanService.expire_due`).
A timed-out decision's fallback is the story's documented default: **deny,
and stop processing further tasks** — handled identically to an explicit
deny for that task, except the orchestrator does not continue past it in
the same call (the caller must explicitly resume to proceed).

## What did *not* change

`AUTO` mode's behavior is byte-for-byte what E14-S1/S2 already did — every
existing test and caller keeps working unchanged. Approval/hybrid pausing
only activates when a caller explicitly opts into a non-`auto` mode.
