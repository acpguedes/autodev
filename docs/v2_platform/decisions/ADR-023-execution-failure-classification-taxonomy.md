# ADR-023: Execution Failure Classification Taxonomy

- **Status:** Accepted
- **Date:** 2026-08-21
- **Authors:** AutoDev platform team
- **Related epic:** E46
- **Supersedes/Relates to:** ADR-021 (execution contracts), E41-S5 (self-repair loop)

## Context

`OrchestratorService._maybe_self_repair` (`backend/orchestrator/service.py:1464-1572`)
fires a bounded Coder repair whenever a validation task's `TaskExecutionOutcome`
is not `"completed"` and the batch wrote at least one file — regardless of
*why* the validation failed. `ExecutionResult`
(`backend/execution/contracts.py:70-133`) carries no failure classification
today: `status`, `error`, `stdout`/`stderr`, and `exit_code` are all it has.
Two independent external code analyses (2026-08-21), re-verified against the
current tree (`943845f` + E43-S8 merge), confirmed zero `failure_kind`-like
fields exist anywhere in `backend/execution/` or `backend/orchestrator/`.

The E42/E43 live runs demonstrated the blast radius: 10/10 validation tasks
failed on a sandbox policy rejection (`Command 'cd' is not in the allowed
list.`) and E41-S5's retry loop reported `failed_after_retry` even though
the generated code was correct — E43-S1 fixed that one parser bug (folding
a `cd <dir> && <cmd>` prefix into the sandbox's `cwd`/`command`), but the
next policy or environment failure (a disallowed command, a missing Docker
daemon, a provisioning error) will misfire self-repair identically: one
wasted Coder call and one wasted re-execution per failed command, and a risk
of the repair agent rewriting **correct** code to chase a failure it cannot
actually fix.

## Decision

Introduce a typed failure taxonomy, set **at the point where a failure
originates** — the sandbox runner, the composite action runner's policy
gates, and the environment manager's provisioning path — never inferred
after the fact by pattern-matching `stderr` in the orchestrator.

`ExecutionFailureKind` (`backend/execution/contracts.py`), a `StrEnum`:

| Kind | Meaning | Origin |
| --- | --- | --- |
| `code_failure` | The command ran to completion under an allowed, provisioned environment and exited non-zero, or an applied patch's post-condition failed. | `SandboxRunner._execute` (docker/local exit code), default fallback in `_run_via_sandbox` |
| `command_not_allowed` | The command's executable is not in the sandbox's allowlist. | `SandboxRunner._execute` |
| `policy_denied` | A governance decision (execution policy, environment filesystem policy, human approval denial/timeout) refused the action. Also covers the sandbox's own workspace-containment check (`cwd` escapes or does not resolve inside the project root) — a containment policy, not a code defect. | `TaskExecutor.dispatch`/`deny_all`, `CompositeActionRunner.run`, `SandboxRunner._resolve_workspace` |
| `environment_unavailable` | No Docker and no local-execution opt-in, or E32 environment provisioning failed (capacity ceiling, backend error). | `SandboxRunner._execute`, `OrchestratorService._process_tasks` (via `TaskExecutor.deny_all`) |
| `dependency_missing` | Reserved for a future producer that can positively identify a missing package/tool (e.g. a package-manager-specific exit code), distinct from a generic non-zero exit. Not yet set by any current origin — additive taxonomy member, not a functional gap for this epic's stories. | — |
| `timeout` | The sandboxed process exceeded its wall-clock budget. | `SandboxRunner._run_docker`/`_run_local` |
| `internal_error` | Reserved for a platform-side exception unrelated to the command or a policy decision (e.g. an unexpected exception in a future producer). Not yet set by any current origin. | — |

`ExecutionResult` gains one additive field, `failure_kind:
ExecutionFailureKind | None = None` — `None` for every success and for
results produced before this change (backward compatible, no migration).
A derived, read-only property, `repairable_by_code_change: bool`, is `True`
if and only if `failure_kind is ExecutionFailureKind.CODE_FAILURE`; it is
not a stored field since it is fully determined by `failure_kind`.

`ValidationResult` (`backend/validation/models.py`) gains the matching
`failure_kind: str | None = None` field (a plain string, not the enum —
`backend/validation` is a lower-layer module `backend/execution` already
depends on, and must not depend back on `backend/execution/contracts`).
`backend.execution.runner._run_via_sandbox` converts the string to
`ExecutionFailureKind` when building the `ExecutionResult`, defaulting an
unclassified failure to `code_failure` (the "process exit codes default to
code_failure" rule), so any current or future `ValidationResult` producer
that does not set `failure_kind` still gets a safe, repair-eligible
classification rather than a silently-dropped one.

The `execution.action.failed` event payload
(`ExecutionActionFailedData`) gains one additive, optional field,
`failureKind: str | None = None`, under the current
`SCHEMA_VERSION_EVENTS = "2.0.0"` — the same append-only discipline E43-S2
used to add `command`/`path`/`stdout`/`stderr`.

## Alternatives considered

1. **Classify by pattern-matching `stderr`/`error` in the orchestrator** —
   rejected: brittle (every sandbox/tooling message format becomes a de
   facto contract), and explicitly the failure mode E46 exists to move away
   from — the origin already knows unambiguously why it failed; matching
   text after the fact can only approximate that.
2. **A single boolean (`repairable: bool`) instead of a taxonomy** — rejected:
   loses the "why" needed for the skip-event UI (E46-S2) and for future
   producers (batched repair diagnostics, E46-S3) to reason about *what*
   kind of non-code failure occurred, not just that repair was skipped.
3. **Store `repairable_by_code_change` as a dataclass field, set alongside
   `failure_kind`** — rejected: a stored, independently-settable field can
   drift from `failure_kind` (a producer could set one without the other);
   deriving it as a property makes the two facts impossible to disagree.

## Consequences

- **Positive:** `ExecutionResult` now carries enough information for E46-S2
  to gate self-repair on "is this actually a code problem" instead of "did
  something fail and were files written"; the skip/repair decision becomes
  a property lookup, not a fresh guess per caller.
- **Negative / trade-offs:** every origin that constructs a failed
  `ExecutionResult`/`ValidationResult` must now decide which kind applies;
  a new origin that forgets to set `failure_kind` silently falls back to
  `code_failure` via the runner's defaulting (safe for self-repair's
  fail-open rollout story, E46-S2-T3, but means a genuinely
  non-repairable new failure mode still repairs until its origin is
  updated to classify it explicitly).
- **Contract impact:** additive only — no `hostApi`/SemVer bump, no schema
  migration; the new event field is additive under the current
  `SCHEMA_VERSION_EVENTS = "2.0.0"`.

## Rollback plan

No feature flag: revert is a plain code revert of the `failure_kind`
field additions, the enum, and the event-schema field. Every consumer
treats an absent `failure_kind` as "unclassified" already (E46-S2's
fail-open rule), so no data migration is needed either direction.

## References

- ADR-021 (`ADR-021-real-task-executor-contracts.md`)
- `docs/v2_platform/phases/e46_failure_classification_self_repair.md`
