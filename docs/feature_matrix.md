# AutoDev Architect — Feature Matrix

This document maps every major feature and module to its current implementation status.

**Status key:**

| Status | Meaning |
|--------|---------|
| `default` | Ships out of the box; no configuration required |
| `optional` | Implemented; requires an environment flag or extra dependency |
| `stub` | Code skeleton exists; raises `NotImplementedError` or is a no-op placeholder |
| `planned` | Not yet implemented; tracked in the roadmap |

For the full list of environment flags see `backend/` source and
[`docs/implementation/patches_and_validation.md`](implementation/patches_and_validation.md).

---

## Persistence

| Feature | Status | Notes |
|---------|--------|-------|
| SQLite persistence | `default` | `backend/persistence/sqlite_adapter.py`; sessions, runs, messages, run-steps, plan documents |
| Repository pattern / Store abstraction | `default` | `backend/persistence/base.py` protocol + `get_store()` factory; landed in Unit 1 |
| PostgreSQL persistence | `stub` | `backend/persistence/postgres_adapter.py` — all methods raise `NotImplementedError`; set `DATABASE_URL=postgresql://…` to select it |
| Schema migrations (versioned) | `default` | `backend/persistence/migrations/`; `MigrationRunner` with `schema_version` table and ordered callables |
| Redis-backed queue/cache/locks | `optional` | `RedisJobQueue` in `backend/jobs/queue.py` plus `backend/coordination/redis.py`; selected with `AUTODEV_JOB_BACKEND=redis`, while in-process/local fallbacks remain the default |
| MinIO artifact storage | `optional` | `backend/artifacts/store.py` provides MinIO/S3 artifacts when `STORAGE_BACKEND=s3`; local filesystem artifacts remain the default |
| pgvector semantic memory | `planned` | Requires PostgreSQL; tracked in roadmap release 0.3 |

---

## LLM Providers

| Feature | Status | Notes |
|---------|--------|-------|
| Stub provider | `default` | `LLM_PROVIDER=stub` (default); deterministic, no paid API needed |
| OpenAI provider | `optional` | `LLM_PROVIDER=openai`; requires `OPENAI_API_KEY`; falls back to stub if key is absent |
| Ollama provider | `optional` | `LLM_PROVIDER=ollama`; uses OpenAI-compatible local endpoint; defaults to `http://localhost:11434/v1` |
| Anthropic / Claude provider | `planned` | Not implemented; no code in `backend/llm/factory.py`; only `stub`, `openai`, and `ollama` are handled |
| Provider caching (LRU) | `default` | LLM factory is LRU-cached per provider+model tuple |

---

## Agent System

| Feature | Status | Notes |
|---------|--------|-------|
| Core agent pipeline (linear) | `default` | Navigator → Analyzer → Architect → Coder → DevOps → Validator → Responder; `backend/orchestrator/service.py` |
| Agent registry + auto-discovery | `default` | `backend/agents/registry.py`; `GET /agents`, `GET /agents/{name}` |
| Typed metadata contracts | `default` | `backend/agents/contracts.py`; `GET /agents/contracts`; fallback keeps output machine-readable |
| Specialized agents (security, refactor, docs) | `default` | `backend/agents/{security,refactor,docs}/`; discoverable but not in default `agent_order` |
| Dynamic multi-agent orchestration | `optional` | `AUTODEV_DYNAMIC_ORCH=1`; `POST /chat/dynamic`; `backend/orchestrator/routing.py` + `graphs.py` |
| Supervisor / feedback loop | `stub` | `SupervisorPolicy` in `backend/orchestrator/routing.py` is defined but not wired into the execution path |
| Agent tool-use loop (read/edit/run) | `planned` | Agents are pure prompt→text; no tool bindings; tracked as Unit 25 in `mvp_refactor_plan.md` |

---

## Repository Intelligence

| Feature | Status | Notes |
|---------|--------|-------|
| File inventory + ranked candidate retrieval | `default` | `GET /repository/context`; `backend/repository/intelligence.py` |
| Lexical symbol extraction (regex) | `default` | `backend/repository/providers/lexical_provider.py`; `GET /repository/symbols` with `AUTODEV_REPO_PROVIDER` unset |
| tree-sitter symbol extraction | `stub` | `AUTODEV_REPO_PROVIDER=treesitter`; `backend/repository/providers/treesitter_provider.py` always delegates to the lexical provider — real AST-based extraction has not been implemented yet, present or absent the `tree_sitter` package |
| Semantic retrieval (pgvector embeddings) | `planned` | Requires PostgreSQL + pgvector; tracked in roadmap release 0.3 |
| Full-text search (PostgreSQL FTS / ripgrep) | `planned` | Tracked in roadmap release 0.3 |
| Repository metadata graph (symbols, edges) | `planned` | Tracked in roadmap releases 0.3 / 1.0 |

---

## Patch Pipeline

| Feature | Status | Notes |
|---------|--------|-------|
| Patch generation (unified diff) | `default` | `backend/patches/engine.py`; `POST /patches/generate`; stdlib `difflib`, no external deps |
| Patch application (dry-run) | `default` | `apply_patch()` dry-runs by default; rejects path traversal outside root |
| Patch application (real write) | `optional` | `AUTODEV_ENABLE_PATCH_APPLY=1`; writes files only when flag is set |
| Patch persistence / versioning | `planned` | No patch rows stored; tracked as Unit 23/24 in `mvp_refactor_plan.md` |
| Orchestrator→patch integration | `planned` | `execute_plan()` uses fake timestamps; does not call `apply_patch()`; tracked as Unit 24 |

---

## Validation / Sandbox

| Feature | Status | Notes |
|---------|--------|-------|
| Validation sandbox (Docker or local subprocess) | `optional` | `AUTODEV_ENABLE_SANDBOX=1`; `backend/validation/sandbox.py`; prefers hardened Docker (`--network=none`, non-root, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, CPU/memory/pids limits); fails closed without Docker unless `AUTODEV_SANDBOX_ALLOW_LOCAL=1` is also set; command allowlist enforced by basename |
| Executable validation pipeline | `optional` | Same flag as above; returns real exit codes and captured output when enabled |
| Validation skipped by default | `default` | Returns `skipped=true, backend="disabled"` unless flag is set |
| Failure classification / rework loop | `planned` | Tracked as Unit 29 in `mvp_refactor_plan.md` |

---

## Plan Approval Workflow

| Feature | Status | Notes |
|---------|--------|-------|
| Plan store (SQLite) | `default` | `backend/plans/store.py`; `plan_documents` table; approve/reject persisted |
| Plan approval API | `default` | `GET/PUT /plans/{id}`, `POST /plans/{id}/approve`, `POST /plans/{id}/reject` |
| Approval gates blocking execution | `planned` | `execute_plan()` does not check plan status before running; tracked as Unit 27 |
| Plan auto-persisted from orchestrator | `planned` | `create_plan()` writes to session store only, not `PlanStore`; tracked as Unit 23 |

---

## Observability

| Feature | Status | Notes |
|---------|--------|-------|
| Request-ID tracing middleware | `default` | Attached via router loader `attach(app)` hook; `backend/observability/` |
| Prometheus metrics endpoint | `default` | `GET /metrics` (Prometheus text); in-process registry |
| OpenTelemetry tracing | `optional` | Used only when `opentelemetry` package is importable; not in `requirements.txt` |
| Structured execution / action trace | `planned` | Tracked as Unit 30 in `mvp_refactor_plan.md` |
| Grafana / Loki dashboards | `planned` | Tracked in roadmap release 0.9 |

---

## Settings / Feature Flags

| Feature | Status | Notes |
|---------|--------|-------|
| Runtime config (`autodev.config.json`) | `default` | `backend/config/runtime.py`; `GET /config`, `PUT /config`; configures LLM provider and project root; API key redacted in responses, file persisted with `0600` permissions (see Security) |
| Feature-flags endpoint (`GET /features`) | `default` | `backend/api/routers/features.py`; returns `Settings.model_dump()` with `openai_api_key` redacted — **partial**: only exposes generic `Settings` fields, not the ~12 `AUTODEV_*` flags that actually gate behavior (sandbox, patch-apply, dynamic-orch, job-backend, repo-provider, cors-origins, api-token, ...), which stay invisible, scattered `os.getenv` reads; the three `feature_*` booleans in `Settings` are hardcoded `True` and unread elsewhere |
| Centralized typed settings module | `default` | `backend/config/settings.py` (`pydantic-settings`, LRU-cached `get_settings()`) — **partial**: wired into only `database_url` and the `/features` endpoint; the ~12 `AUTODEV_*` flags above have not been migrated off scattered `os.getenv`/`os.environ` calls; full migration + local/prod profiles tracked under v2 epic E0-S1 |
| CORS configuration (env-driven) | `default` | `backend/api/main.py` `_cors_allowed_origins()`; override with `AUTODEV_CORS_ORIGINS` (comma-separated); defaults to `localhost:3000` / `127.0.0.1:3000`; methods/headers restricted (`GET,POST,PUT,OPTIONS` / `Authorization,Content-Type`) rather than wildcarded |

---

## Security

| Feature | Status | Notes |
|---------|--------|-------|
| Bearer-token API authentication | `optional` | `AUTODEV_API_TOKEN`; `backend/api/security.py` global FastAPI dependency; no-op when unset (open by default for local dev); constant-time `hmac.compare_digest`; `/health`, `/docs`, `/redoc`, `/openapi.json` stay public even when a token is configured |
| Secret redaction (`/config`, `/features`) | `default` | `GET`/`PUT /config` redact the stored LLM API key to `***` (`backend/config/runtime.py`); re-submitting `***` preserves the previously stored key; `/features` separately redacts `openai_api_key` |
| `autodev.config.json` file permissions | `default` | `RuntimeConfigService.save()` chmods the config file to `0600` after every write (best-effort) |
| Filesystem path confinement (`/repository/symbols`) | `default` | `backend/api/routers/repo_symbols.py` resolves `?path=` against the configured project root and returns `403` on traversal outside it; the patch engine enforces the same guard |
| Sandbox hardening + fail-closed execution | `optional` | See Validation / Sandbox below; same `AUTODEV_ENABLE_SANDBOX` / `AUTODEV_SANDBOX_ALLOW_LOCAL` flags |

See [`docs/security.md`](security.md) for the full threat model and residual risks (no dependency lockfile, mutable base image tags, no frontend CSP/HSTS headers).

---

## Skills Subsystem

| Feature | Status | Notes |
|---------|--------|-------|
| Skills registry + auto-discovery | `default` | `backend/skills/registry.py`; `GET /skills`, `GET /skills/{name}`, `POST /skills/{name}/invoke` |
| Built-in skills | `default` | `summarize_diff`, `extract_symbols_lexical`, `render_checklist`; deterministic, no LLM needed |
| Skills CLI | `default` | `autodev skills list / invoke` |

---

## Async Jobs

| Feature | Status | Notes |
|---------|--------|-------|
| In-process job queue | `default` | `ThreadPoolExecutor`-backed; `POST /jobs`, `GET /jobs/{id}` |
| Redis job queue | `optional` | `RedisJobQueue` persists job state in Redis and runs registered handlers; activated by `AUTODEV_JOB_BACKEND=redis` |

---

## Streaming / Real-time

| Feature | Status | Notes |
|---------|--------|-------|
| SSE run stream endpoint | `planned` | `GET /sessions/{id}/runs/{run_id}/stream` tracked as Unit 6 in `mvp_refactor_plan.md` |
| Real-time streaming UI | `planned` | Frontend console currently polls; tracked as Unit 13 |

---

## Frontend

| Feature | Status | Notes |
|---------|--------|-------|
| Next.js 14 App Router UI | `default` | Six pages: `/` (chat), `/config`, `/agents`, `/plans`, `/skills`, `/patches` |
| Dark-theme only (pure CSS) | `default` | `frontend/styles/globals.css` (757 lines); `ThemeProvider` forces `defaultTheme="dark"`, `enableSystem={false}`, no toggle UI |
| Tailwind CSS + shadcn/ui | `default` | Unit 11 landed: `tailwind.config.ts`, `ThemeProvider.tsx` (next-themes) wraps every page, one shadcn primitive (`components/ui/button.tsx`) — **foundation/shell only**: zero pages or components import Tailwind utility classes or `Button` yet; all six pages still render via bespoke `globals.css` classNames. Adoption tracked as Units 12–18 |
| Plan approval UI (interactive) | `planned` | Current plan page is read-only; tracked as Unit 15 |
| Diff viewer | `planned` | Current patch view is a plain `<pre>`; tracked as Unit 14 |
| Run history panel | `planned` | `RunHistoryPanel.tsx` exists but is never rendered; tracked as Unit 16 |
| Observability dashboard | `planned` | Tracked as Unit 17 |
| Light/dark toggle | `planned` | Unit 11 wired `ThemeProvider` (next-themes) but hardcoded `defaultTheme="dark"`, `enableSystem={false}`; no toggle component exists yet |

---

## CI Pipeline

| Feature | Status | Notes |
|---------|--------|-------|
| Backend CI (ruff + mypy + pytest) | `default` | GitHub Actions; `make check-backend` |
| Frontend CI (lint + typecheck + vitest) | `default` | GitHub Actions; `make check-frontend` |
| Coverage gates | `default` | `.github/workflows/ci-backend.yml`; `pytest --cov=backend --cov-fail-under=60` |
| Smoke e2e job (boot + health check) | `default` | `.github/workflows/ci-backend.yml` `smoke-e2e` job: boots `uvicorn`, polls `/health`, asserts HTTP 200 |
| Infra / docs validation | `planned` | No docker-compose/terraform lint or docs-link-check step in CI yet; tracked as Unit 22 |

---

## Infrastructure / Self-Hosting

| Feature | Status | Notes |
|---------|--------|-------|
| Docker Compose (backend + frontend) | `default` | `infrastructure/docker-compose.yml`; boots with `LLM_PROVIDER=stub` |
| Production-like Compose profile (Postgres + Redis + MinIO) | `optional` | `infrastructure/docker-compose.yml --profile prod` starts `backend-prod` with PostgreSQL, Redis, and MinIO wiring |
| Kubernetes deployment | `planned` | `terraform/main.tf` is a placeholder; tracked in roadmap release 1.0 |

---

*Last updated: 2026-07-04, as part of closing E0-S6 Redis/MinIO/local fallback
foundations. See `docs/v2_platform/progress.md` for the current v2 story tracker
and `git log` for full history.*
