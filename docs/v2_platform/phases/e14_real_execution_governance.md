# E14 — Real Task Execution & Governed Autonomy

**Wave:** Beta (anchors the Beta exit criterion "a real plan -> code -> apply
patch -> validate in sandbox -> evaluate flow runs with RBAC, fail-closed
budgets, and end-to-end traces"). S1-S4 (executor, policy engine, execution
modes, sandbox runners) can start once E3's core and E9-S1 land, without
waiting on all of E11; S5 (Web UX) additionally depends on E10; S6-S7
(shell/CLI) can proceed in parallel once S3 lands.
**Status:** Done · **Stories:** 7/7 complete (E14-S1..S7 done, see below)
**Depends on:** E2, E3, E9-S1, E11-S4; environment layer provided by E32
(Beta cut of the isolated execution environment)
**Enables:** the Beta exit criterion's real execution flow; consumed by E10
(approval/execution screens, via E14-S5)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §12.7-§12.10,
§18.5, §18.7.8, §18.8, §18.9

**Scope boundary (Beta):** E14 owns *what* runs (ExecutionTask/Action,
permission & approval policy, governed autonomy) and the runner contract
(E14-S4). *Where* it runs — the environment abstraction, fail-closed
network/filesystem policy, lifecycle and isolation audit — is **E32**
(`phases/e32_isolated_execution_beta.md`, ADR-013). Packaging, global
install and upgrade of the `autodev` CLI/platform are **E34**
(`phases/e34_packaging_global_install.md`, ADR-015); E14-S6/S7 keep the CLI
command UX only.

## Objective

Turn agent-generated plans/`ExecutionTask`s into real, auditable actions
(create/edit files, apply patches, run commands, run validations) under an
explicit permission/policy layer with three execution modes (approval, auto,
hybrid), wired securely to the Execution Sandbox, exposed through both the Web
UI and a governed interactive shell, and installable via an `autodev` CLI
command.

## Key result

`execute_plan` stops being a simulation that only marks steps completed and
instead invokes a real, policy-mediated Task Executor whose result
(stdout/stderr/exit code/diffs/artifacts) is persisted and linked to the
run/session/task. The operator picks the execution mode (approval/auto/hybrid)
and can grant persistent, revocable dynamic permissions.

## Stories

### E14-S1 — Real Task Executor — **Complete** (2026-08-17)

Subtasks:
- `E14-S1-T1`: `ExecutionAction` contract (create_file/edit_file/apply_patch/run_command/run_validation) and `ExecutionResult` contract (stdout/stderr/exit_code/diff/artifacts). **Done** — `backend/execution/contracts.py`.
- `E14-S1-T2`: executor that maps an `ExecutionTask`/Flow step to one or more `ExecutionAction`s and dispatches them to the appropriate runner, replacing `execute_plan`'s simulated loop. **Done** — `backend/execution/executor.py` (`TaskExecutor`), `backend/execution/runner.py` (`InProcessActionRunner`, reusing the E0 patch engine and the v1 `SandboxRunner` precursor per ADR-021); wired into `OrchestratorService._execute_plan_run`.
- `E14-S1-T3`: persistence of results linked to run_id/step_id/task_id and `execution.action.started`/`.completed`/`.failed` events. **Done** — results ride in `AgentExecution.metadata["actions"]` (persisted via the existing `run.results` column); three additive events in `backend/events/catalog.py` (37 → 40 types).

RFC-009 (`docs/v2_platform/decisions/RFC-009-execution-action-contract.md`) and
ADR-021 (`docs/v2_platform/decisions/ADR-021-real-task-executor-contracts.md`)
were filed before implementation, per the epic exit checklist. Full design
notes: `docs/execution/engine.md`. Scope boundary: the task → action mapping
is a deliberately simple category heuristic (current agents produce
free-text descriptions, not structured file/command data); no
permission/policy engine (E14-S2), no execution modes (E14-S3), and no
hardened per-action-type sandboxing (E14-S4) yet.

| Criterion | Detail |
| --- | --- |
| Functional | An `ExecutionTask` with a file/patch/command action produces a real, observable result (diff applied, command run, exit code captured); an interrupted execution preserves partial state |
| Non-functional | Every action is auditable (who, when, what, result); no silent action outside the trace |
| DoR (specific) | Execution flow-node contract (E3) and a base Execution Sandbox (E11-S4, or the v1 precursor `backend/validation/sandbox.py`) available |
| DoD (specific) | Test coverage per action type; `docs/execution/engine.md`; RFC+ADR if the contract is a MAJOR change (agent_guide.md §5) |
| Dependencies | E2-S3, E3-S2, E9-S1 |

### E14-S2 — Permission & Policy Engine — **Complete** (2026-08-17)

Subtasks:
- `E14-S2-T1`: policy model — allow/deny list per action category (shell, fs-write, patch, network, secrets-read, validation), scoped to project/repository/session. **Done** — `backend/execution/policy.py` (`PolicyRule`, `PolicyCategory`, `PolicyScopeKind`, `ACTION_TYPE_TO_POLICY_CATEGORY`).
- `E14-S2-T2`: fail-closed policy evaluator — no action without an explicit policy entry is permitted. **Done** — `PolicyService.evaluate` wired into `TaskExecutor`; production fails closed without a stored rule (`PolicyMissingError`), local/dev falls back to a permissive default (mirrors `QuotaService`, ADR-019) to preserve the Alpha gate's local-first guarantee.
- `E14-S2-T3`: audit trail — every decision (allowed/denied/pending) recorded with actor and reason. **Done** — `execution_policy_decisions` table + `execution.policy.allowed`/`.denied` events (42 catalog types).

RFC-010 + ADR-022 filed before implementation. REST: `GET/POST
/v2/execution/policy` (`policy:read`/`policy:admin`). Full design notes,
including the specificity-based precedence rule and its fail-closed
tie-break: `docs/execution/permissions.md`. Scope boundary: dynamic
permission REST endpoints land with E14-S3 (which is what actually grants
them); `network`/`secrets-read` categories are declared but no runner
emits them yet.

| Criterion | Detail |
| --- | --- |
| Functional | An action with no matching policy entry is denied by default; a project-scoped allow rule permits equivalent future actions; every decision is logged and auditable |
| Non-functional | Policy evaluation < 50 ms; no implicit permission; evaluator errors fail closed |
| DoR (specific) | Action-category taxonomy defined (from E14-S1); basic RBAC (E11-S2) or a local stub |
| DoD (specific) | Default-deny and scope tests; `docs/execution/permissions.md` |
| Dependencies | E14-S1, E11-S2 |

### E14-S3 — Execution Modes: Approval, Auto, Hybrid — **Complete** (2026-08-17)

Subtasks:
- `E14-S3-T1`: approval mode — every sensitive action pauses for a human decision (reuses the E3-S4 human-in-the-loop node). **Done** — `backend/execution/decisions.py` (`DecisionService`) reuses E3-S4's pause/decide/expire *pattern* (E3-S4 itself is bound to the Flow Engine's run/node model, not `OrchestratorService`'s; see `docs/execution/modes.md`) and the existing `run.human.requested`/`.resolved` events.
- `E14-S3-T2`: auto mode — automatically executes anything the E14-S2 policy already allows. **Done** — unchanged from S1/S2, now one of three explicit `ExecutionMode` values (`backend/execution/modes.py`), and the default so existing callers are unaffected.
- `E14-S3-T3`: hybrid mode — auto-executes what's allowed; for anything else, offers the 3-option decision (run once / run and persist a dynamic permission for similar actions / deny) and persists the grant when option 2 is chosen. **Done** — `OrchestratorService.resolve_execution_decision(..., persist_as_rule=True)`.

| Criterion | Detail |
| --- | --- |
| Functional | Given hybrid mode and a command not covered by policy, the system prompts with the 3 documented options and, on "always", persists a reusable dynamic rule (e.g. `sqlite *`) with no further prompt for equivalent future actions |
| Non-functional | A pending decision does not block unrelated independent actions; a decision timeout expires into a configurable fallback route (default: deny and stop the run), reusing E3-S4-T3 |
| DoR (specific) | E14-S2 available; E3-S4 human-decision contract reviewed |
| DoD (specific) | Test of all 3 modes and all 3 response options; dynamic permissions reviewable/revocable via API; `docs/execution/modes.md` |
| Dependencies | E14-S1, E14-S2, E3-S4 |

### E14-S4 — Sandbox-Backed Runners — **Complete** (2026-08-17)

Subtasks:
- `E14-S4-T1`: command (shell) runner via `SandboxRunner` (hardened Docker, no network by default, allowlist). **Done** — `CommandRunner` (`backend/execution/runner.py`).
- `E14-S4-T2`: patch runner (apply with path guard and dry-run) — hardened, kept separate from the arbitrary-command runner. **Done** — `PatchRunner`; no code path from it into `subprocess`.
- `E14-S4-T3`: validation runner — reuses the existing Validation Gates; local fallback only behind explicit `AUTODEV_SANDBOX_ALLOW_LOCAL=1`. **Done** — `ValidationRunner`.

`CompositeActionRunner` dispatches by action type to the three; `InProcessActionRunner`
(E14-S1's original name) is now a backward-compatible alias for it — same
constructor signature, same contract, no caller changes needed. Reused the
existing E11-S4 real-Docker contract test
(`backend/tests/integration/test_sandbox_security_contract.py`, one new
assertion that `CommandRunner` routes through the identical `SandboxPolicy`)
rather than duplicating it; added a new fail-closed-without-Docker unit test
at the `ExecutionAction` layer. Docs: `docs/execution/engine.md`.

| Criterion | Detail |
| --- | --- |
| Functional | A command-type `ExecutionAction` runs in the no-network sandbox; a patch-type action applies with path guard and never falls back to arbitrary exec; validation reuses the existing Validation Gate |
| Non-functional | Sandbox has no network by default; fails closed without Docker; clear separation of responsibility across the 3 runners |
| DoR (specific) | `backend/validation/sandbox.py` (E11-S4 / v1 precursor) reviewed; action taxonomy from E14-S1 |
| DoD (specific) | Reused sandbox-escape test; fail-closed-without-Docker test; docs |
| Dependencies | E14-S1, E11-S4 |

### E14-S5 — Web UX for Governed Execution — **Complete** (2026-08-17)

Subtasks:
- `E14-S5-T1`: plan/action view, inline approve/deny, before/after diffs. **Done, with a scope note** — `/execution` (`ActionApprovalPanel`) offers approve-once/approve-always/deny; no *pre-approval* diff preview (the backend has nothing to preview before an action runs — the diff/log appears in the execution log once it has). See `docs/execution/web-ux.md`.
- `E14-S5-T2`: real-time logs (stdout/stderr/exit code) via the E9-S2 streaming transport. **Done** — `ExecutionActionLog`/`lib/execution_events.ts`, a new small module (not an extension of `lib/timeline.ts`, whose fixed 4-stage model doesn't fit `execution.action.*` payloads — documented in `docs/execution/web-ux.md`); the SSE transport itself needed no server changes.
- `E14-S5-T3`: dynamic permission management (list/revoke) and pause/cancel/resume of runs. **Done for list/revoke and resume**; **cancel not built** — E14-S3 never shipped a cancel endpoint, so there is nothing for a cancel button to call.

| Criterion | Detail |
| --- | --- |
| Functional | An operator approves/denies an action from the Web UI and sees the result in real time; can revoke a previously saved dynamic permission; can pause/cancel/resume a running run |
| Non-functional | WCAG 2.2 AA; log streaming starts < 1 s (inherited from E9-S2) |
| DoR (specific) | E10 (base Design System), E9-S2 (streaming), and redesigned shell/screens from E15–E17 available |
| DoD (specific) | End-to-end approve/deny UI test; a11y audit; docs |
| Dependencies | E14-S2, E14-S3, E9-S2, E10, E15, E16, E17 |

### E14-S6 — Governed Interactive Shell (`autodev --shell`) — **Complete** (2026-08-17)

Subtasks:
- `E14-S6-T1`: REPL loop that consumes only the Control Plane API (`/v2`), never the State Store directly (API-first). **Done** — `backend/cli_shell.py`; a static-analysis contract test parses its own AST and fails on any `backend.*` import. `backend/cli.py`'s pre-existing subcommands still call the orchestrator in-process — they predate this contract and were not rewritten (see `docs/execution/shell.md`).
- `E14-S6-T2`: inline confirmation of sensitive actions and terminal log streaming. **Done, with a scope note** — inline confirmation via the same approve/approve-always/deny vocabulary as the Web UX (E14-S5); no *live SSE* streaming in the shell (the synchronous execute/resume response already carries every result, printed as a condensed summary — see `docs/execution/shell.md`).
- `E14-S6-T3`: support for all 3 modes (approval/auto/hybrid) and condensed diff/result summaries in the terminal. **Done** — `--mode auto|approval|hybrid`.

| Criterion | Detail |
| --- | --- |
| Functional | `autodev --shell` starts a conversational loop that executes actions with approval per the active mode, shows condensed diffs, and streams logs |
| Non-functional | Zero direct calls to Postgres/Redis/MinIO from the shell (API-first, §2.13); approval UX parity with the Web UI |
| DoR (specific) | E14-S3 (modes) and E9-S1 (API) available |
| DoD (specific) | Contract test "shell only calls `/v2`"; `docs/execution/shell.md` |
| Dependencies | E14-S3, E9-S1 |

### E14-S7 — `autodev` CLI Packaging & Install — **Complete** (2026-08-17)

Subtasks:
- `E14-S7-T1`: packaged entry point (`autodev` on PATH/bin) via Python packaging (console script) or an equivalent OSS installer. **Done — already existed**: `backend/pyproject.toml`'s `[project.scripts] autodev = "backend.cli:main"` predates this story; no new packaging mechanism was needed.
- `E14-S7-T2`: default behavior (`autodev`) starts the web/local experience and opens the browser when possible; flags `--shell`, `--command "<text>"`, `--mode approval|auto|hybrid`, and a permission config/persistence subcommand. **Done** — no-args starts uvicorn + opens the browser at E18's existing root descriptor; `--command` now works standalone (not only with `--shell`); `autodev permissions list|revoke` mirrors E14-S5's dynamic-permissions panel over HTTP.
- `E14-S7-T3`: self-hosted installation guide (no mandatory paid-service dependency). **Done** — `docs/execution/cli-install.md`.

| Criterion | Detail |
| --- | --- |
| Functional | Installing the package registers `autodev` on PATH; `autodev` with no args starts web/local and opens the browser; `autodev --shell`, `autodev --command "..."`, and `autodev --mode <mode>` behave as specified |
| Non-functional | 100% self-hosted install by default; no mandatory paid infrastructure dependency |
| DoR (specific) | E14-S6 (shell) and E9-S1 (API) available; packaging choice (setuptools/uv/pipx) recorded in a lightweight ADR if it changes current distribution |
| DoD (specific) | Local (container/dev) install test verifying the entry point; `docs/execution/cli-install.md` |
| Dependencies | E14-S6, E14-S1, E14-S4 |

## v1 precursor / starting point

- `backend/orchestrator/service.py::OrchestratorService.execute_plan` is the
  closest existing analogue — but it is a pure simulation: it iterates
  `ExecutionTask`s and marks each `RunStep` as `COMPLETED` without creating a
  file, applying a patch, or running a command. It must evolve into the real
  executor (E14-S1), not be treated as already satisfying this epic.
- `backend/validation/sandbox.py::SandboxRunner` is a real, flag-gated,
  hardened runner (`AUTODEV_ENABLE_SANDBOX`, Docker no-network by default,
  command allowlist, fail-closed without Docker unless
  `AUTODEV_SANDBOX_ALLOW_LOCAL=1`) — today wired only into validation jobs.
  E14-S4 extends this into three distinct runners (command/patch/validation)
  reused by the real executor.
- There is no permission/policy engine, no execution-mode selection, no
  dynamic-permission persistence, no governed interactive shell, and no
  packaged `autodev` CLI entry point today — E14-S2, S3, S5, S6, S7 start from
  zero.

## Epic exit checklist

- [x] All 7 stories meet the global DoD (`../templates/dod_checklist.md`) plus
      their story-specific DoD above.
- [x] Contract tests green for the `ExecutionAction`/`ExecutionResult`
      contracts, the policy evaluator, and the sandbox-backed runners.
- [x] An RFC + ADR are filed before E14-S1 implementation starts, per
      `agent_guide.md` §5 (new public contracts: execution actions/results,
      permission policy schema). RFC-009/ADR-021 (S1), RFC-010/ADR-022 (S2).
- [x] `docs/v2_platform/progress.md` updated.
- [ ] Beta exit criterion "real plan -> code -> apply patch -> validate in
      sandbox -> evaluate flow runs with RBAC, fail-closed budgets, and
      end-to-end traces" satisfied (§18.9). E14 delivers the real
      plan->code->apply-patch->validate-in-sandbox path with fail-closed
      budgets (E14-S2 policy) and RBAC (E11-S2, already enforced on every
      `/v2` route); "evaluate" is E5's concern, not E14's. Walking this
      wave-exit gate needs a dedicated evidence pass across every Beta
      anchor epic (E4, E5, E6, E7, E8-S3/S4, E9-S2/S3/S4, E10, E11, E14),
      mirroring how the Alpha gate was walked only once every Alpha anchor
      epic was Done — left open here rather than claimed without that
      evidence.
