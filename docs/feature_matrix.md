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
| PostgreSQL persistence | `optional` | `backend/persistence/postgres_adapter.py` `PostgresStore` — sessions/runs/messages/plans with migrations (E0-S3); selected via `DATABASE_URL=postgresql://…`; requires `psycopg` |
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

## Agent System (v1 linear pipeline)

The rows below describe the frozen v1 agent generation. The contracted v2 agent
generation is in the **Agent Framework (v2)** section further down.

| Feature | Status | Notes |
|---------|--------|-------|
| Core agent pipeline (linear) | `default` | Navigator → Analyzer → Architect → Coder → DevOps → Validator → Responder; `backend/orchestrator/service.py` |
| Agent registry + auto-discovery (v1) | `default` | `backend/agents/registry.py`; `GET /agents`, `GET /agents/{name}` |
| Typed metadata contracts | `default` | `backend/agents/contracts.py`; `GET /agents/contracts`; fallback keeps output machine-readable |
| Specialized agents (security, refactor, docs) | `default` | `backend/agents/{security,refactor,docs}/`; discoverable but not in default `agent_order` |
| Dynamic multi-agent orchestration | `optional` | `AUTODEV_DYNAMIC_ORCH=1`; `POST /chat/dynamic`; `backend/orchestrator/routing.py` + `graphs.py` |
| Supervisor / feedback loop | `stub` | `SupervisorPolicy` in `backend/orchestrator/routing.py` is defined but not wired into the execution path |
| Agent tool-use loop (read/edit/run) | `planned` | Agents are pure prompt→text; no tool bindings; tracked as Unit 25 in `mvp_refactor_plan.md` |

---

## Plugin System (v2)

Delivered by v2 epic E1 (Plugin Core & SDK). See
[`docs/plugins/`](plugins/) for the manifest, permissions, and registry docs.

| Feature | Status | Notes |
|---------|--------|-------|
| `plugin.yaml` manifest + extension-point catalog | `default` | `backend/plugins/manifest.py` + `backend/plugins/catalog.py`; published JSON schema; validated on load (E1-S1) |
| Plugin Host discovery + lifecycle | `default` | `backend/plugins/host.py`; directory/entry-point discovery, durable install/enable/disable/uninstall, `hostApi` compatibility rejection, isolated load failures (E1-S2) |
| Plugin permission isolation | `default` | `backend/plugins/permissions.py`; default-deny fs/net/exec/secrets model, brokered Host API access, `plugin.permission.denied` audit events (E1-S3) |
| Python SDK + scaffolding + contract tests | `default` | `backend/sdk/`; SemVer-versioned contracts, `sdk new plugin` scaffolding, plugin contract-test harness, runnable example plugin (E1-S4) |
| Active-plugin registry | `default` | `backend/plugins/registry.py`; `GET /v2/plugins/active` with `schemaVersion`; consistency after enable/disable, safe dev hot-reload rollback (E1-S5) |

---

## Agent Framework (v2)

Delivered by v2 epic E2 (Agent Framework). See [`docs/agents/`](agents/) for the
manifest, registry, and runtime docs.

| Feature | Status | Notes |
|---------|--------|-------|
| `agent.yaml` manifest validator | `default` | `backend/agents/manifest.py`; versioned manifest, strict typed IO validation with safe default budgets, published SDK contract + JSON schema (E2-S1) |
| Agent Registry + catalog API | `default` | `backend/agents/registry_v2.py`; `GET /v2/agents/catalog`; SemVer resolution across versions, rankable capability search, deprecation signaling, Plugin Host sync (E2-S2) |
| Agent Runtime (fail-closed budgets + guardrails) | `default` | `backend/agents/runtime.py`; execution cycle with fail-closed token/cost/step/tool-call budgets, output denylist guardrails, per-step trace + token/cost metrics (E2-S3) |
| Permissioned tool broker + provider abstraction | `default` | `backend/agents/tools.py` + `backend/agents/provider.py`; permissioned tool/skill mediation, default network denial, offline stub LLM provider + provider protocol, per-call metering by run/tenant (E2-S4) |
| Packaged reference agent plugin | `default` | `autodev/agent-coder` packaged as an installable agent plugin registered through the Plugin Host and Agent Registry, with runtime parity coverage (E2-S5) |

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
| Feature-flags endpoint (`GET /features`) | `default` | `backend/api/routers/features.py`; returns `Settings.redacted_model_dump()`. The `AUTODEV_*` flags are now typed fields on `Settings` (`autodev_enable_sandbox`, `autodev_enable_patch_apply`, `autodev_dynamic_orch`, `autodev_job_backend`, `autodev_repo_provider`, `autodev_cors_origins`, …), so they surface here rather than only via scattered `os.getenv` reads |
| Centralized typed settings module | `default` | `backend/config/settings.py` (`pydantic-settings`, LRU-cached `get_settings()`); local/prod profiles, JSON-file-then-env precedence, `validate_profile()`, `redacted_model_dump()`, and the `autodev config validate` CLI landed in v2 epic E0-S2. Some legacy call sites still read `os.getenv` directly (e.g. `backend/patches/engine.py`, `backend/validation/sandbox.py`); those are being migrated onto `Settings` incrementally |
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
| Default HTTP security headers | `default` | Backend emits `Content-Security-Policy`, `Permissions-Policy`, `Referrer-Policy`, `X-Content-Type-Options`, `X-Frame-Options` by default (E0-S5) |
| HSTS header (opt-in) | `optional` | `Strict-Transport-Security` emitted only when `AUTODEV_ENABLE_HSTS=true`, so local HTTP is not pinned to HTTPS (E0-S5) |
| Secret-scan + SCA CI gate | `default` | `make run_secret_scanning` (dependency-free scanner) plus a Trivy filesystem SCA gate in backend CI; PRs fail on detected secrets or `CRITICAL` CVEs (E0-S5); baseline in [`docs/security/baseline.md`](security/baseline.md) |
| Plugin permission isolation | `default` | Default-deny fs/net/exec/secrets model for plugins with brokered Host API access and `plugin.permission.denied` audit events (E1-S3); see [`docs/plugins/permissions.md`](plugins/permissions.md) |

See [`docs/security.md`](security.md) for the full threat model and residual risks (no dependency lockfile, mutable base image tags, no frontend-specific CSP/HSTS headers in `next.config.mjs` — backend headers now ship by default).

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

*Last updated: 2026-07-04, adding the Plugin System (v2, E1) and Agent Framework
(v2, E2) sections, correcting the PostgreSQL and typed-settings rows, and adding
the E0-S5/E1-S3 security rows. See `docs/v2_platform/progress.md` for the current
v2 story tracker and `git log` for full history.*
