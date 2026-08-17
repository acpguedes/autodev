# Real Task Execution Engine (E14-S1)

> Canonical decisions: RFC-009 (`docs/v2_platform/decisions/RFC-009-execution-action-contract.md`)
> and ADR-021 (`docs/v2_platform/decisions/ADR-021-real-task-executor-contracts.md`).
> Story definition: `docs/v2_platform/phases/e14_real_execution_governance.md#e14-s1`.

## What changed

`OrchestratorService.execute_plan` used to be a simulation: it iterated the
derived `ExecutionTask`s and marked every `RunStep` `COMPLETED` without
creating a file, applying a patch, or running a command. E14-S1 replaces
that loop with a real, auditable executor.

## Contracts (`backend/execution/contracts.py`)

- `ExecutionActionType`: `create_file`, `edit_file`, `apply_patch`,
  `run_command`, `run_validation`.
- `ExecutionAction`: one unit of real work — an action type plus a
  type-specific payload (path/content, a `Patch`, or a command/cwd).
- `ExecutionResult`: the outcome — status (`succeeded`/`failed`),
  stdout/stderr/exit_code, a unified diff, touched artifact paths, and
  timestamps. `to_dict()` renders it JSON-safely.

## Task → action mapping (`backend/execution/executor.py`)

`TaskExecutor.execute()` maps one `ExecutionTask` to zero or more actions,
dispatches each to an injected `ActionRunner`, and emits
`execution.action.started`/`.completed`/`.failed` per action
(`backend/events/catalog.py`).

The S1 mapping is deliberately simple — the current planner/coder/validator
agents (`backend/agents/coder/agent.py`, `backend/agents/validator/agent.py`)
produce free-text task descriptions, not structured file or command data:

- `category == "validation"`: if the description names a known tool
  (`pytest`, `ruff`, `npm`, `python`, `python3`), dispatch one
  `run_validation` action running that tool through the sandbox. Otherwise no
  action is derived.
- `category == "implementation"`: dispatch one `create_file` action that
  writes the task's title/description to
  `.autodev/execution-notes/<task_id>.md`. This is an honest record of real
  work rather than fabricated source code — the coder agent does not yet
  produce real diffs (that depends on real LLM-backed code generation,
  out of scope for this story).
- `planning`/`analysis`/`architecture`/`operations`: no action is derived
  yet.

A task that maps to no actions still produces a `completed` `RunStep`
(unchanged from the prior behavior for those categories). A task with at
least one failed action produces a `failed` `RunStep` — `StepStatus` gained
a `FAILED` member for this. `OrchestratorRun.status` at the top level is
unaffected: the run itself still completes once every task has been
attempted; failure is visible at the step/action level
(`AgentExecution.metadata["actions"]` carries every `ExecutionResult`).

## Runner (`backend/execution/runner.py`)

`InProcessActionRunner` is the S1 runner. It does not introduce new
sandboxing — it reuses:

- `backend.patches.engine` (`generate_patch`/`apply_patch`) for
  `create_file`/`edit_file`/`apply_patch`, with its existing
  path-traversal guard (independently re-checked before the file is even
  read, so a traversal attempt cannot leak host file content into a diff)
  and its existing `AUTODEV_ENABLE_PATCH_APPLY` fail-closed gate (dry-run by
  default; `InProcessActionRunner(enable_writes=True)` overrides this
  explicitly, e.g. for tests).
- `backend.validation.sandbox.SandboxRunner` for `run_command`/
  `run_validation`, wrapped in a `ValidationJob`. This stays disabled by
  default (`AUTODEV_ENABLE_SANDBOX=0`) and fails closed without Docker,
  exactly as it already did for validation jobs.

E14-S4 replaces this with three dedicated, hardened runners
(command/patch/validation) behind the same `ActionRunner` protocol — the
`ExecutionAction`/`ExecutionResult` contract does not change when that
happens.

## Scope boundary

Out of scope for E14-S1, by design:

- **Permission/policy engine** (E14-S2): every action that is successfully
  *derived* executes unconditionally today; there is no allow/deny policy
  yet.
- **Execution modes** (E14-S3): there is no approval/auto/hybrid selection;
  `execute_plan` runs every derived action synchronously.
- **Hardened, per-action-type sandboxing** (E14-S4): `InProcessActionRunner`
  inherits the v1 sandbox's limitations (one Docker image, no per-action
  timeout tuning).
- **Real code generation**: the `implementation` category writes an
  execution-note file, not source code, until the coder agent produces
  actual diffs.
