# E14 — Real Task Execution & Governed Autonomy

**Wave:** Beta (anchors the Beta exit criterion "a real plan -> code -> apply
patch -> validate in sandbox -> evaluate flow runs with RBAC, fail-closed
budgets, and end-to-end traces"). S1-S4 (executor, policy engine, execution
modes, sandbox runners) can start once E3's core and E9-S1 land, without
waiting on all of E11; S5 (Web UX) additionally depends on E10; S6-S7
(shell/CLI) can proceed in parallel once S3 lands.
**Status:** Not started · **Stories:** 0/7 complete
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

### E14-S1 — Real Task Executor

Subtasks:
- `E14-S1-T1`: `ExecutionAction` contract (create_file/edit_file/apply_patch/run_command/run_validation) and `ExecutionResult` contract (stdout/stderr/exit_code/diff/artifacts).
- `E14-S1-T2`: executor that maps an `ExecutionTask`/Flow step to one or more `ExecutionAction`s and dispatches them to the appropriate runner, replacing `execute_plan`'s simulated loop.
- `E14-S1-T3`: persistence of results linked to run_id/step_id/task_id and `execution.action.started`/`.completed`/`.failed` events.

| Criterion | Detail |
| --- | --- |
| Functional | An `ExecutionTask` with a file/patch/command action produces a real, observable result (diff applied, command run, exit code captured); an interrupted execution preserves partial state |
| Non-functional | Every action is auditable (who, when, what, result); no silent action outside the trace |
| DoR (specific) | Execution flow-node contract (E3) and a base Execution Sandbox (E11-S4, or the v1 precursor `backend/validation/sandbox.py`) available |
| DoD (specific) | Test coverage per action type; `docs/execution/engine.md`; RFC+ADR if the contract is a MAJOR change (agent_guide.md §5) |
| Dependencies | E2-S3, E3-S2, E9-S1 |

### E14-S2 — Permission & Policy Engine

Subtasks:
- `E14-S2-T1`: policy model — allow/deny list per action category (shell, fs-write, patch, network, secrets-read, validation), scoped to project/repository/session.
- `E14-S2-T2`: fail-closed policy evaluator — no action without an explicit policy entry is permitted.
- `E14-S2-T3`: audit trail — every decision (allowed/denied/pending) recorded with actor and reason.

| Criterion | Detail |
| --- | --- |
| Functional | An action with no matching policy entry is denied by default; a project-scoped allow rule permits equivalent future actions; every decision is logged and auditable |
| Non-functional | Policy evaluation < 50 ms; no implicit permission; evaluator errors fail closed |
| DoR (specific) | Action-category taxonomy defined (from E14-S1); basic RBAC (E11-S2) or a local stub |
| DoD (specific) | Default-deny and scope tests; `docs/execution/permissions.md` |
| Dependencies | E14-S1, E11-S2 |

### E14-S3 — Execution Modes: Approval, Auto, Hybrid

Subtasks:
- `E14-S3-T1`: approval mode — every sensitive action pauses for a human decision (reuses the E3-S4 human-in-the-loop node).
- `E14-S3-T2`: auto mode — automatically executes anything the E14-S2 policy already allows.
- `E14-S3-T3`: hybrid mode — auto-executes what's allowed; for anything else, offers the 3-option decision (run once / run and persist a dynamic permission for similar actions / deny) and persists the grant when option 2 is chosen.

| Criterion | Detail |
| --- | --- |
| Functional | Given hybrid mode and a command not covered by policy, the system prompts with the 3 documented options and, on "always", persists a reusable dynamic rule (e.g. `sqlite *`) with no further prompt for equivalent future actions |
| Non-functional | A pending decision does not block unrelated independent actions; a decision timeout expires into a configurable fallback route (default: deny and stop the run), reusing E3-S4-T3 |
| DoR (specific) | E14-S2 available; E3-S4 human-decision contract reviewed |
| DoD (specific) | Test of all 3 modes and all 3 response options; dynamic permissions reviewable/revocable via API; `docs/execution/modes.md` |
| Dependencies | E14-S1, E14-S2, E3-S4 |

### E14-S4 — Sandbox-Backed Runners

Subtasks:
- `E14-S4-T1`: command (shell) runner via `SandboxRunner` (hardened Docker, no network by default, allowlist).
- `E14-S4-T2`: patch runner (apply with path guard and dry-run) — hardened, kept separate from the arbitrary-command runner.
- `E14-S4-T3`: validation runner — reuses the existing Validation Gates; local fallback only behind explicit `AUTODEV_SANDBOX_ALLOW_LOCAL=1`.

| Criterion | Detail |
| --- | --- |
| Functional | A command-type `ExecutionAction` runs in the no-network sandbox; a patch-type action applies with path guard and never falls back to arbitrary exec; validation reuses the existing Validation Gate |
| Non-functional | Sandbox has no network by default; fails closed without Docker; clear separation of responsibility across the 3 runners |
| DoR (specific) | `backend/validation/sandbox.py` (E11-S4 / v1 precursor) reviewed; action taxonomy from E14-S1 |
| DoD (specific) | Reused sandbox-escape test; fail-closed-without-Docker test; docs |
| Dependencies | E14-S1, E11-S4 |

### E14-S5 — Web UX for Governed Execution

Subtasks:
- `E14-S5-T1`: plan/action view, inline approve/deny, before/after diffs.
- `E14-S5-T2`: real-time logs (stdout/stderr/exit code) via the E9-S2 streaming transport.
- `E14-S5-T3`: dynamic permission management (list/revoke) and pause/cancel/resume of runs.

| Criterion | Detail |
| --- | --- |
| Functional | An operator approves/denies an action from the Web UI and sees the result in real time; can revoke a previously saved dynamic permission; can pause/cancel/resume a running run |
| Non-functional | WCAG 2.2 AA; log streaming starts < 1 s (inherited from E9-S2) |
| DoR (specific) | E10 (base Design System), E9-S2 (streaming), and redesigned shell/screens from E15–E17 available |
| DoD (specific) | End-to-end approve/deny UI test; a11y audit; docs |
| Dependencies | E14-S2, E14-S3, E9-S2, E10, E15, E16, E17 |

### E14-S6 — Governed Interactive Shell (`autodev --shell`)

Subtasks:
- `E14-S6-T1`: REPL loop that consumes only the Control Plane API (`/v2`), never the State Store directly (API-first).
- `E14-S6-T2`: inline confirmation of sensitive actions and terminal log streaming.
- `E14-S6-T3`: support for all 3 modes (approval/auto/hybrid) and condensed diff/result summaries in the terminal.

| Criterion | Detail |
| --- | --- |
| Functional | `autodev --shell` starts a conversational loop that executes actions with approval per the active mode, shows condensed diffs, and streams logs |
| Non-functional | Zero direct calls to Postgres/Redis/MinIO from the shell (API-first, §2.13); approval UX parity with the Web UI |
| DoR (specific) | E14-S3 (modes) and E9-S1 (API) available |
| DoD (specific) | Contract test "shell only calls `/v2`"; `docs/execution/shell.md` |
| Dependencies | E14-S3, E9-S1 |

### E14-S7 — `autodev` CLI Packaging & Install

Subtasks:
- `E14-S7-T1`: packaged entry point (`autodev` on PATH/bin) via Python packaging (console script) or an equivalent OSS installer.
- `E14-S7-T2`: default behavior (`autodev`) starts the web/local experience and opens the browser when possible; flags `--shell`, `--command "<text>"`, `--mode approval|auto|hybrid`, and a permission config/persistence subcommand.
- `E14-S7-T3`: self-hosted installation guide (no mandatory paid-service dependency).

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

- [ ] All 7 stories meet the global DoD (`../templates/dod_checklist.md`) plus
      their story-specific DoD above.
- [ ] Contract tests green for the `ExecutionAction`/`ExecutionResult`
      contracts, the policy evaluator, and the sandbox-backed runners.
- [ ] An RFC + ADR are filed before E14-S1 implementation starts, per
      `agent_guide.md` §5 (new public contracts: execution actions/results,
      permission policy schema).
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Beta exit criterion "real plan -> code -> apply patch -> validate in
      sandbox -> evaluate flow runs with RBAC, fail-closed budgets, and
      end-to-end traces" satisfied (§18.9).
