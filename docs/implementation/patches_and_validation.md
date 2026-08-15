# Patches, validation, jobs, observability & repository intelligence

These subsystems are additive and, where they execute side effects, **disabled by default
behind environment flags** so the platform stays safe and self-hostable.

## Patch engine (`backend/patches/`, `backend/api/routers/patches.py`, `backend/cli_plugins/patches.py`)

- `generate_patch(path, original, updated) -> Patch` — unified diff via stdlib `difflib`.
- `apply_patch(patch, root=".", enable=None) -> PatchResult` — **dry-run by default**; writes
  only when `enable=True` or `AUTODEV_ENABLE_PATCH_APPLY=1`. Rejects path traversal outside `root`.

```bash
curl -X POST localhost:8000/patches/generate -H 'Content-Type: application/json' \
  -d '{"path":"f.py","original":"a\n","updated":"b\n"}'
autodev patches generate --path f.py --original-file old.py --updated-file new.py
```

## Validation sandbox (`backend/validation/`, `backend/api/routers/validation.py`, `backend/cli_plugins/validation.py`)

- `SandboxRunner().run(ValidationJob(...)) -> ValidationResult`. **Disabled by default**
  (`skipped=true, backend="disabled"`); enable with `AUTODEV_ENABLE_SANDBOX`. All sandbox
  decisions come from one typed `SandboxPolicy` (`sandbox_policy_from_settings()`), not raw
  `os.environ` reads (E11-S4).
- When enabled it prefers Docker (`python:3.11-slim`), hardened: `--network=none` by default
  (override with `AUTODEV_SANDBOX_DOCKER_NETWORK`), non-root `--user=65534:65534`,
  `--cap-drop=ALL`, `--security-opt=no-new-privileges`, CPU/memory/pids limits, a **read-only
  root filesystem** with a bounded `/tmp`, and a **read-only mount of only the resolved,
  guarded workspace** — `job.cwd` is resolved against `AUTODEV_PROJECT_ROOT` and rejected
  (`backend="blocked"`, no process spawned) if it escapes that root (E11-S4).
- Every job has a bounded timeout (`AUTODEV_SANDBOX_TIMEOUT_SECONDS`, default 300s); a killed
  job returns code `124` with a sanitized message, not a hang (E11-S4).
- **Without Docker**, the runner falls back to a local subprocess only when
  `AUTODEV_SANDBOX_ALLOW_LOCAL=1` is explicitly set — the default is fail-closed, not a silent
  unsandboxed fallback. Local execution still runs only inside the guarded workspace.
- A command allowlist (`pytest`, `ruff`, `npm`, `python`) is enforced regardless of backend.
- The real-Docker security contract
  (`backend/tests/integration/test_sandbox_security_contract.py`) is a mandatory CI gate —
  network denial, workspace-only filesystem exposure, and no privilege escalation must all pass
  with zero skips (`.github/workflows/ci-backend.yml`, `security-baseline` job).

```bash
curl -X POST localhost:8000/validation/run -H 'Content-Type: application/json' \
  -d '{"command":["pytest","-q"]}'          # -> skipped unless AUTODEV_ENABLE_SANDBOX=1
autodev validate run -- pytest -q
```

## Async jobs (`backend/jobs/`, `backend/api/routers/jobs.py`)

- `AbstractJobQueue` with an in-process `ThreadPoolExecutor` implementation by default; an
  optional `RedisJobQueue` activates only when `redis` is importable and
  `AUTODEV_JOB_BACKEND=redis`. `get_queue()` returns the in-process queue by default.

```bash
curl -X POST localhost:8000/jobs -H 'Content-Type: application/json' \
  -d '{"job_type":"echo","payload":{"msg":"hi"}}'
curl localhost:8000/jobs/<job_id>
```

## Observability (`backend/observability/`, `backend/api/routers/metrics.py`)

- Request-ID + structured logging middleware (attached automatically via the router loader's
  `attach(app)` hook) and an in-process metrics registry.
- `GET /metrics` — Prometheus text exposition. OpenTelemetry is used only when importable.

## Repository intelligence providers (`backend/repository/providers/`, `backend/api/routers/repo_symbols.py`)

- A pluggable `RepositoryProvider`; `get_provider()` returns the lexical provider by default
  and a tree-sitter provider only when `tree_sitter` is importable and
  `AUTODEV_REPO_PROVIDER=treesitter`. The existing `RepositoryIntelligenceService` is unchanged.
- `GET /repository/symbols?code=...&language=python` — extract top-level symbols.

## Optional dependencies

`tree_sitter`, `redis`, and OpenTelemetry packages are **optional** — they are intentionally
NOT in `backend/requirements.txt` so the core install stays minimal and free of paid/heavy
infrastructure. Install them only to opt into the corresponding provider/backend.
