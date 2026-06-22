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
| Redis-backed state / queue | `stub` | `RedisJobQueue` in `backend/jobs/queue.py` raises `NotImplementedError`; in-process `ThreadPoolExecutor` queue is the default |
| MinIO artifact storage | `planned` | Not yet wired; tracked in roadmap milestone 1.0 |
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
| tree-sitter symbol extraction | `optional` | `AUTODEV_REPO_PROVIDER=treesitter`; requires `pip install tree-sitter`; `backend/repository/providers/treesitter_provider.py` — falls back to lexical when package absent |
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
| Validation sandbox (Docker or local subprocess) | `optional` | `AUTODEV_ENABLE_SANDBOX=1`; `backend/validation/sandbox.py`; prefers Docker, falls back to subprocess; command allowlist enforced |
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
| Runtime config (`autodev.config.json`) | `default` | `backend/config/runtime.py`; `GET /config`, `PUT /config`; configures LLM provider and project root |
| Feature-flags endpoint (`GET /features`) | `planned` | Tracked as Unit 4 in `mvp_refactor_plan.md`; env flags currently scattered via `os.getenv` |
| Centralized typed settings module | `planned` | Tracked as Unit 4; `pydantic-settings` not yet introduced |
| CORS configuration (env-driven) | `planned` | CORS origins are hardcoded to `localhost:3000` in `backend/api/main.py`; env override tracked as Unit 5 |

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
| Redis job queue | `stub` | `RedisJobQueue` in `backend/jobs/queue.py` raises `NotImplementedError`; activated by `AUTODEV_JOB_BACKEND=redis` and importable `redis` package |

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
| Dark-theme only (pure CSS) | `default` | `frontend/styles/globals.css`; ~695 lines; no component library |
| Tailwind CSS + shadcn/ui | `planned` | Tracked as Unit 11–18 in `mvp_refactor_plan.md` |
| Plan approval UI (interactive) | `planned` | Current plan page is read-only; tracked as Unit 15 |
| Diff viewer | `planned` | Current patch view is a plain `<pre>`; tracked as Unit 14 |
| Run history panel | `planned` | `RunHistoryPanel.tsx` exists but is never rendered; tracked as Unit 16 |
| Observability dashboard | `planned` | Tracked as Unit 17 |
| Light/dark toggle | `planned` | Tracked as Unit 11 |

---

## CI Pipeline

| Feature | Status | Notes |
|---------|--------|-------|
| Backend CI (ruff + mypy + pytest) | `default` | GitHub Actions; `make check-backend` |
| Frontend CI (lint + typecheck + vitest) | `default` | GitHub Actions; `make check-frontend` |
| Coverage gates | `planned` | Tracked as Unit 22 in `mvp_refactor_plan.md` |
| Smoke e2e job (boot + health check) | `planned` | Tracked as Unit 22 |
| Infra / docs validation | `planned` | Tracked as Unit 22 |

---

## Infrastructure / Self-Hosting

| Feature | Status | Notes |
|---------|--------|-------|
| Docker Compose (backend + frontend) | `default` | `infrastructure/docker-compose.yml`; boots with `LLM_PROVIDER=stub` |
| Full-stack Compose profile (Postgres + Redis + MinIO + Ollama) | `planned` | Tracked as Unit 20 in `mvp_refactor_plan.md` |
| Kubernetes deployment | `planned` | `terraform/main.tf` is a placeholder; tracked in roadmap release 1.0 |

---

*Last updated: 2026-06-22. Reflects Unit 1 (Repository pattern + SQLite adapter) as the most recently merged unit.*
