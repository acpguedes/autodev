# RFC-009: Execution Action & Result Contract

- **Status:** Accepted
- **Author(s):** AutoDev platform team          **Date:** 2026-08-17
- **Reviewers:** N/A (single-session review)
- **Epic(s):** E14                 **Stories:** E14-S1, E14-S4 (runner hardening)
- **Comment deadline:** 2026-08-17

## Summary

Introduce two new platform contracts — `ExecutionAction` and
`ExecutionResult` — plus three new event types
(`execution.action.started`/`.completed`/`.failed`) so that
`OrchestratorService.execute_plan` performs real work (file writes, patch
application, command execution, validation runs) instead of the current
simulation that marks every `RunStep` `COMPLETED` without doing anything.

## Motivation

`backend/orchestrator/service.py::_execute_plan_run` iterates the derived
`ExecutionTask`s and fabricates a `status: "completed"` result per task with
no filesystem or process side effect. This blocks the Beta exit criterion
("a real plan -> code -> apply patch -> validate in sandbox -> evaluate flow
runs with RBAC, fail-closed budgets, and end-to-end traces", reference doc
§18.9) and is called out by name as a simulation, not an implementation, in
`docs/v2_platform/phases/e14_real_execution_governance.md`'s "v1 precursor"
section. E14-S1 is the first story of Epic E14 and needs a stable contract
for the action types a task can produce and the result shape callers and
downstream stories (policy engine E14-S2, execution modes E14-S3, hardened
runners E14-S4, Web UX E14-S5) depend on.

## Proposed design

New module `backend/execution/contracts.py`:

- `ExecutionActionType(StrEnum)`: `create_file`, `edit_file`, `apply_patch`,
  `run_command`, `run_validation` — the five action kinds named in the E14-S1
  story definition.
- `ExecutionAction` (frozen dataclass): `action_id`, `type`, `task_id`,
  `step_key`, plus a type-specific payload (`path`/`content` for
  create/edit-file; a `backend.patches.models.Patch` for apply_patch;
  `command`/`cwd` for run_command; a `backend.validation.models.ValidationJob`
  for run_validation).
- `ExecutionResult` (dataclass): `action_id`, `task_id`, `step_key`,
  `status` (`succeeded`/`failed`), `stdout`, `stderr`, `exit_code`, `diff`,
  `artifacts: list[str]`, `started_at`, `completed_at`,
  `error: str | None`, with a `to_dict()` for JSON-safe persistence,
  following the existing `RunStep.to_dict()` pattern.

Runners are pluggable behind an `ActionRunner` protocol
(`run(action) -> ExecutionResult`) so the contract does not couple to any one
execution backend. E14-S1 ships `InProcessActionRunner`, which does **not**
introduce new sandboxing: it reuses `backend.patches.engine.generate_patch` /
`apply_patch` (existing path-traversal guard) for file/patch actions, and
wraps `run_command`/`run_validation` into a `ValidationJob` dispatched to the
existing `backend.validation.sandbox.SandboxRunner` (flag-gated, fail-closed
without Docker, path-guarded workspace). E14-S4 later replaces/hardens this
with three dedicated runners (command/patch/validation) behind the same
`ActionRunner` protocol — the contract does not change when that happens.

`TaskExecutor` (`backend/execution/executor.py`) maps one `ExecutionTask` to
one or more `ExecutionAction`s and dispatches each to the injected runner,
replacing the simulated loop inside
`OrchestratorService._execute_plan_run`. `OrchestratorRun`/`RunStep`/
`AgentExecution` — the response shapes the three existing API/CLI callers
depend on — are unchanged; `ExecutionResult` fields are folded into
`AgentExecution.metadata`, the extensibility point those shapes already use.
`StepStatus` gains a `FAILED` member so a failed action is reported as such
instead of always `COMPLETED`.

Three new event types are added to `EVENT_CATALOG`
(`backend/events/catalog.py`), additive to `SCHEMA_VERSION_EVENTS = "2.0.0"`,
mirroring the existing `RunStepStarted/Completed/Failed` trio:
`execution.action.started`, `execution.action.completed`,
`execution.action.failed`.

### Contracts and compatibility
- **API change:** none directly — `OrchestratorRun.to_dict()` is unchanged;
  `ExecutionResult` data rides inside the existing `AgentExecution.metadata`
  field, which is already an open `Mapping[str, Any]`.
- **hostApi/SemVer change:** none — `ExecutionAction`/`ExecutionResult` are
  internal backend contracts, not an SDK extension point, so no `hostApi`
  bump is implied. New event types are additive under the current
  `SCHEMA_VERSION_EVENTS`.
- **Data migrations:** none — no new persisted tables in S1; execution
  results ride inside the existing `run.results`/`run.steps` JSON columns.

## Alternatives considered

1. **Extend `ExecutionTask` in place with result fields** instead of a
   separate `ExecutionResult` — rejected: conflates the plan-time task
   description with a run-time outcome, and would not generalize to a task
   producing multiple actions (e.g. a code-change task that both edits a
   file and runs a validation).
2. **Skip the contract, wire `SandboxRunner` directly into the orchestrator**
   — rejected: couples the orchestrator to one runner implementation and
   forecloses E14-S2 (policy engine) and E14-S4 (hardened runner split) from
   intercepting/replacing execution without touching orchestrator internals.

## Impact

- **Security / RBAC / permissions:** none new in S1 — action execution still
  runs through the existing `SandboxRunner` fail-closed policy and the patch
  engine's path-traversal guard; no permission/policy engine yet (that is
  E14-S2).
- **Observability (traces/metrics/events):** three new event types; no new
  metrics in S1.
- **Cost / budgets / quotas:** unaffected — the existing per-tenant run
  admission (E11-S3) already gates `execute_plan` before this change.
- **Accessibility (if UI):** N/A, backend-only story.
- **Performance / SLOs:** unaffected; action dispatch is synchronous and
  bounded by the existing sandbox timeout.

## Implementation and rollout plan

Single story (E14-S1), no feature flag — `execute_plan` is not on any public
compatibility contract that requires a staged rollout, and the change is
additive at the event-catalog and metadata level.

## Open questions

None — S1 is scoped narrowly enough (in-process runner, no policy engine
yet) that decision-quality open questions are limited to the ones policy
(E14-S2) and hardened runners (E14-S4) resolve in their own stories.
