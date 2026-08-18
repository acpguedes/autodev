# `autodev` CLI Packaging & Install (E14-S7, E34-S1)

> Story definitions: `docs/v2_platform/phases/e14_real_execution_governance.md#e14-s7`,
> `docs/v2_platform/phases/e34_packaging_global_install.md#e34-s1`.

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

## Packaging (E34-S1, ADR-015 Accepted)

`[project.scripts] autodev = "backend.cli:main"` is a **strategy-agnostic
entry point**: `pip install -e backend/`, `pipx install backend/`, and
`uv tool install backend/` all resolve it identically. ADR-015 (Accepted)
chose a hybrid strategy — this pip-compatible package for the `autodev` CLI,
plus the existing `docker-compose` bundle (`make container-up-full`) for the
self-hosted platform — over a bespoke installer script; see the ADR for the
full options table and rationale.

- **`autodev --version`**: prints `{"version", "commit", "build_date"}` as
  JSON (`backend/ops/version.py`). `version` comes from installed package
  metadata; `commit`/`build_date` are `"unknown"` for a plain source
  install, or set via `AUTODEV_BUILD_COMMIT`/`AUTODEV_BUILD_DATE` by a
  packaging step that wants reproducible build provenance baked into the
  artifact.
- **Clean-environment install verification**: `scripts/verify_clean_install.sh`
  builds a wheel from `backend/`, installs it into a fresh virtualenv, and
  runs `autodev --version` / `autodev config validate` from a temp directory
  outside the repo — proving the install path with no repo checkout, no
  editable install, and no accidental reliance on the current working
  directory.

## Self-host bootstrap & storage posture (E34-S2)

- **`autodev doctor`**: read-only preflight diagnostics
  (`backend/ops/doctor.py`), in a fixed order — `settings` (profile/storage
  consistency, via the existing `Settings.validate_profile` fail-closed
  validator), `port` (configured `AUTODEV_HOST`/`AUTODEV_PORT` free to
  bind), `project_root` (writable), `database` (SQLite parent dir writable,
  or a real bounded-timeout PostgreSQL connection), `storage_backend`
  (local artifact dir writable, or `AUTODEV_MINIO_ENDPOINT` set for `s3`).
  Prints `{"status", "checks": [{"name", "status", "detail"}, ...]}`; exits
  `1` if any check fails. When `settings` itself fails, the remaining
  checks are skipped (they need valid settings to know what to probe) —
  the JSON output has exactly one check, not five failures.
- **`autodev bootstrap`**: runs the same preflight (`backend/ops/bootstrap.py`),
  and on success initializes the configured state store (SQLite or
  PostgreSQL schema migrations, applied as a side effect of constructing
  the store — the same idempotent migration runner every other entry point
  uses). Fails closed: a failing preflight check touches no state and is
  reported the same way `doctor` reports it. Safe to re-run.
- **Storage posture** is explicit configuration, not a silent fallback:
  `AUTODEV_PROFILE=local` requires a `sqlite://` `DATABASE_URL` and
  `STORAGE_BACKEND=local`; `AUTODEV_PROFILE=prod` requires
  `postgresql://`/`postgres://` and `STORAGE_BACKEND=s3` with MinIO
  credentials set (`backend/config/settings.py::validate_profile`, a
  pydantic `model_validator` that raises rather than defaulting either
  side). `autodev config validate --profile <local|prod>` and
  `autodev doctor` both surface this — there is no configuration state in
  which the storage backend is chosen implicitly.
- **Secrets**: bootstrap never accepts or writes a plaintext secret value.
  A deployment that needs secrets present creates them out-of-band via
  `autodev secrets create` (E33-S1, value read from stdin only) before or
  after bootstrap; bootstrap itself has no secret-material surface.

## Scope reduction (stated, not hidden)

No standalone binary or native OS installer (e.g. a single-file executable,
a Homebrew formula, an MSI) was built in this pass — `pip install -e
backend/` is the documented, tested install path. A packaging choice like
that would be its own ADR-worthy decision (per the story's own DoR:
"packaging choice ... recorded in a lightweight ADR if it changes current
distribution") and wasn't warranted for what the existing `[project.scripts]`
entry point already delivers correctly.
