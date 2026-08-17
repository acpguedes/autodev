# ADR-021: Real Task Executor Contracts and Runner Boundary

- **Status:** Accepted
- **Date:** 2026-08-17
- **Authors:** AutoDev platform team
- **Related epic:** E14
- **Supersedes/Relates to:** RFC-009

## Context

`OrchestratorService.execute_plan` is a simulation: it marks every derived
`ExecutionTask` `COMPLETED` without creating a file, applying a patch, or
running a command (`backend/orchestrator/service.py::_execute_plan_run`).
E14 (Real Task Execution & Governed Autonomy) exists to replace it with a
real, policy-mediated executor across 7 stories. E14-S1 is the first story
and needs a stable contract for what an execution action is and what its
result looks like before the policy engine (S2), execution modes (S3), and
hardened sandbox runners (S4) can build on it. The epic's own exit checklist
requires this ADR (and RFC-009) before S1 implementation starts, since
`ExecutionAction`/`ExecutionResult` are new public contracts.

A real Execution Sandbox already exists as a v1 precursor
(`backend/validation/sandbox.py::SandboxRunner` — flag-gated, Docker-backed,
fail-closed without Docker, no network by default), and a patch engine
already exists (`backend/patches/engine.py` — path-traversal-guarded,
flag-gated writes). Both are wired only into validation jobs and the
patch-review API today, not into real task execution.

## Decision

Adopt `ExecutionAction` / `ExecutionResult` (`backend/execution/contracts.py`)
as the platform's execution contract: five action types (`create_file`,
`edit_file`, `apply_patch`, `run_command`, `run_validation`), and a result
carrying `stdout`/`stderr`/`exit_code`/`diff`/`artifacts`/`status`. Execution
is dispatched through an `ActionRunner` protocol so the contract is decoupled
from any one backend.

For E14-S1, ship `InProcessActionRunner`, which **reuses existing
infrastructure rather than building new sandboxing**:
`backend.patches.engine` for file/patch actions, and
`backend.validation.sandbox.SandboxRunner` (wrapped via
`backend.validation.models.ValidationJob`) for command/validation actions.
E14-S4 later hardens this into three dedicated runners behind the same
`ActionRunner` protocol — the contract itself does not change.

`TaskExecutor` replaces the simulated loop in
`OrchestratorService._execute_plan_run`, keeping `OrchestratorRun`/
`RunStep`/`AgentExecution` externally unchanged (results ride in
`AgentExecution.metadata`) so the three existing callers
(`backend/api/routers/sessions_v2.py`, `backend/api/main.py`,
`backend/cli.py`) need no changes. `StepStatus` gains `FAILED`. Three
additive event types (`execution.action.started/.completed/.failed`) are
added to `EVENT_CATALOG` under the current `SCHEMA_VERSION_EVENTS`.

## Alternatives considered

1. **Wire `SandboxRunner` directly into the orchestrator, no new contract**
   — rejected: couples the orchestrator to one execution backend and blocks
   E14-S2/S4 from intercepting or replacing execution without touching
   orchestrator internals.
2. **Build hardened per-action-type sandboxing in S1** (i.e., do E14-S4's
   job now) — rejected: E14-S4 is explicitly scoped as its own story with
   its own DoD (sandbox-escape test, fail-closed-without-Docker test); S1's
   DoR only requires "a base Execution Sandbox... available," which the v1
   precursor already satisfies.

## Consequences

- **Positive:** `execute_plan` performs real work for the first time in v2;
  downstream E14 stories (policy engine, execution modes, hardened runners)
  get a stable contract to build against without touching orchestrator
  internals again.
- **Negative / trade-offs:** `InProcessActionRunner` inherits the v1
  sandbox's limitations (single hardcoded Docker image, no per-action
  timeout tuning) until E14-S4 lands; there is still no permission/policy
  layer, so any successfully-mapped action executes unconditionally (E14-S2
  closes this gap).
- **Contract impact:** additive only — no `hostApi`/SemVer bump, no schema
  migration; new event types are additive under the current
  `SCHEMA_VERSION_EVENTS = "2.0.0"`.

## Rollback plan

No feature flag: `execute_plan`'s public shape (`OrchestratorRun.to_dict()`)
is unchanged, so a revert is a plain code revert of
`backend/execution/*`, the orchestrator call site, and the three new event
catalog entries, with no data migration to undo.

## References
- RFC-009 (`RFC-009-execution-action-contract.md`)
- `docs/v2_platform/phases/e14_real_execution_governance.md`
