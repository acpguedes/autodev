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
  (`skipped=true, backend="disabled"`); enable with `AUTODEV_ENABLE_SANDBOX`. When enabled it
  prefers Docker (`python:3.11-slim`) and falls back to a local subprocess, with a command
  allowlist (`pytest`, `ruff`, `npm`, `python`).

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
