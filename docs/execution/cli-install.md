# `autodev` CLI Packaging & Install (E14-S7)

> Story definition: `docs/v2_platform/phases/e14_real_execution_governance.md#e14-s7`.

## Install

No new packaging mechanism was needed — `backend/pyproject.toml` already
declares the console-script entry point:

```toml
[project.scripts]
autodev = "backend.cli:main"
```

Local install (this repo has no root `pyproject.toml`; the backend package
is what ships):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e backend/
autodev --help
```

No mandatory paid-service dependency: local mode defaults to SQLite + the
stub LLM provider (the same local-first guarantee E0/E12's Alpha gate
already verifies) — `autodev` runs fully self-hosted out of the box.

## Behavior

- **`autodev`** (no args): starts `backend.api.main:app` under uvicorn on a
  background thread, waits for `/health`, then opens the default browser
  at the API root (`http://127.0.0.1:8000/` by default —
  `AUTODEV_HOST`/`AUTODEV_PORT` override). The root route already exists
  (E18's front door): browsers get a CSP-clean pointer page linking to the
  real product UI (`AUTODEV_UI_URL`) — E14-S7 does not bundle or serve the
  Next.js frontend itself, it reuses that existing descriptor. Runs until
  `Ctrl+C`.
- **`autodev --shell`**: the governed interactive shell (E14-S6).
- **`autodev --command "<goal>"`**: the shell's one-shot round trip
  (create session, run, resolve any pause) without entering the REPL —
  works standalone, `--shell` is not required.
- **`autodev --mode auto|approval|hybrid`**: execution mode for `--shell`/
  `--command` (E14-S3).
- **`autodev permissions list` / `permissions revoke <id>`**: CLI mirror of
  E14-S5's dynamic-permissions panel — `GET`/`DELETE
  /v2/execution/policy/dynamic` over HTTP, the same API-only style as the
  shell (not a direct `PolicyService` call).

Every pre-existing subcommand (`config`, `quotas`, `sessions`, `plan`,
`run`, `repository`, `artifacts`, `sdk`) is unchanged.

## Scope reduction (stated, not hidden)

No standalone binary or native OS installer (e.g. a single-file executable,
a Homebrew formula, an MSI) was built in this pass — `pip install -e
backend/` is the documented, tested install path. A packaging choice like
that would be its own ADR-worthy decision (per the story's own DoR:
"packaging choice ... recorded in a lightweight ADR if it changes current
distribution") and wasn't warranted for what the existing `[project.scripts]`
entry point already delivers correctly.
