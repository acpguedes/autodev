# Governed Interactive Shell — `autodev --shell` (E14-S6)

> Story definition: `docs/v2_platform/phases/e14_real_execution_governance.md#e14-s6`.

## Contract: API-only

`backend/cli_shell.py` talks **only** to the Control Plane API (`/v2`) over
HTTP (`httpx`). It never imports `backend.orchestrator`, `backend.execution`,
`backend.persistence`, or any other `backend.*` module. Enforced by a
static-analysis test that parses the module's own AST and fails on any
`backend.*` import:
`backend/tests/unit/cli/test_cli_shell_api_only.py::test_cli_shell_never_imports_other_backend_modules`.

This is a **new** code path, not a rewrite of the existing subcommands.
`backend/cli.py`'s pre-existing subcommands (`config`, `quotas`, `sessions`,
`plan`, `run`, `repository`, `artifacts`, `sdk`) still call
`OrchestratorService`/`RepositoryIntelligenceService` in-process — they
predate E14-S6's contract, and migrating them onto `/v2` is a separate,
unscoped concern.

## Flow

1. `autodev --shell` (or `python -m backend.cli_shell`) prompts for a goal.
2. `POST /v2/sessions` creates the session.
3. `POST /v2/sessions/{id}/turns` drives the agent pipeline (planner →
   navigator/analyzer → architect → coder → devops → validator) — required
   before execution: the plan is derived from artifacts this pipeline
   produces, not from session creation alone.
4. `POST /v2/sessions/{id}/execution-plan/execute?mode=<mode>` runs the
   plan (E14-S3's three modes, selected via `--mode`).
5. A condensed per-task summary prints (`[status] task_id`, plus any
   diff/error excerpt from `results[].metadata.actions`).
6. If the run comes back `awaiting_approval`, the pending decision's prompt
   is shown inline; the operator answers `approve` / `approve-always` /
   `deny`, which resolves it via `POST /v2/execution/decisions/{id}/resolve`
   and the shell calls `POST .../execution-plan/resume` to continue — the
   same approve/deny/always vocabulary the Web UX (E14-S5) uses.

`--command "<goal>"` runs one goal non-interactively and exits (the
one-shot equivalent E14-S7's CLI packaging reuses).

## Scope note: no live SSE streaming in the shell

The story's DoD mentions "terminal log streaming." The synchronous
execute/resume response already carries every task's result (diffs/stdout
via `metadata.actions`), which the shell prints as a condensed summary
without needing to hold an SSE connection open past run completion (there
is no clean signal for "the stream is done, stop reading" beyond the run's
own synchronous response). Real-time streaming for the shell — reusing the
exact SSE consumption pattern E14-S5's Web UX already proved
(`frontend/lib/execution_events.ts`) — is a reasonable follow-up, not built
in this pass.
