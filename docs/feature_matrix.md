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
| PostgreSQL persistence (State Store only) | `optional` | `backend/persistence/postgres_adapter/` `PostgresStore` — sessions/runs/messages/plans with migrations (E0-S3); selected via `DATABASE_URL=postgresql://…`; requires `psycopg`. **Partial (verified 2026-08-22):** covers the State Store, plus the eight dual-dialect stores (flows, events, artifacts, auth, plugins, repository indexing) now sharing one dialect contract (`backend/persistence/contract.py`, E49, ADR-025) instead of eight hand-rolled copies. `QuotaStore`, `SecretStore`, `PolicyStore`, and `EnvironmentStore` still raise `ValueError` on a `postgresql://` URL and `StepApprovalStore` still diverts to `./autodev_plan_step_state.db` — porting those five onto the new contract is E51-E55, tracked by E48-E60 (`docs/v2_platform/postgres_production_completeness.md`) |
| Schema migrations (versioned) | `default` | `backend/persistence/migrations/`; `MigrationRunner` with `schema_version` table and ordered callables. Covers the core State Store, plan, and code-chunk tables; the 13 domain tables listed in E50 are created by `CREATE TABLE IF NOT EXISTS` outside the runner and are not version-tracked |
| Durable Event Store | `default` | `backend/events/store.py` (E8-S2): append-only `events` table ordered per partition plus transactional `event_projections` materialization; every canonical envelope published on the Event Bus persists when `AUTODEV_EVENT_STORE_ENABLED=true` (default); run reconstruction via `EventStore.reconstruct_run()`; retention/compaction via `AUTODEV_EVENT_RETENTION_DAYS` |
| Redis-backed queue/cache/locks | `optional` | `RedisJobQueue` in `backend/jobs/queue.py` plus `backend/coordination/redis.py`; selected with `AUTODEV_JOB_BACKEND=redis`, while in-process/local fallbacks remain the default |
| MinIO artifact storage | `optional` | `backend/artifacts/store.py` provides MinIO/S3 artifacts when `STORAGE_BACKEND=s3`; local filesystem artifacts remain the default |
| pgvector semantic memory | `optional` | `backend/repository/embeddings/pgvector_store.py` + `backend/repository/embeddings/provider.py`; PostgreSQL + pgvector-backed embedding storage and top-k query (E7-S2/S3). **Requires a pgvector-capable image:** the shipped Compose `prod` profile uses stock `postgres:16-alpine` (`infrastructure/docker-compose.yml:116`), against which the `CREATE EXTENSION vector` migration (`postgres_versions.py:253`) cannot succeed — E48 |

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
| Supervisor / feedback loop | `stub` | `SupervisorPolicy` (`backend/orchestrator/routing.py`) is **superseded** by E5's policy-driven Router/Selector (`backend/routing/`) and will not be wired — it is a sequential cursor that ignores run state, with no cost policy, capability matching, or evaluation feedback. The Router/Selector that replaces it is implemented but is itself not yet wired into `POST /chat/dynamic`, so the adaptive supervisor loop (validator-failure branch-back, bounded iteration) still does not exist in any path |
| Agent tool-use loop (read/edit/run) | `default` | The v1 linear pipeline agents themselves are still pure prompt→text, but real tool bindings now exist and are wired into task execution: E2-S4's `AgentToolBroker` (`backend/agents/tools.py`) mediates permissioned tool/skill access, and E14's governed executor (`backend/execution/executor.py` + `runner.py`) maps tasks to real `create_file`/`edit_file`/`apply_patch`/`run_command`/`run_validation` actions dispatched to `PatchRunner`/`CommandRunner`/`ValidationRunner` |

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

## Orchestration Engine (v2 Flows)

Delivered by v2 epic E3 (Orchestration Engine), Done 6/6. See
[`docs/v2_platform/phases/e3_orchestration_engine.md`](v2_platform/phases/e3_orchestration_engine.md).

| Feature | Status | Notes |
|---------|--------|-------|
| `flow.yaml` declarative graph manifest | `default` | `backend/flows/model.py` (`FlowManifest`); node/conditional-edge schema, cycle/IO validation, versioning (E3-S1) |
| Flow Engine execution (durable Run/Step state) | `default` | `backend/flows/engine.py` (`FlowEngine`), `backend/flows/handlers.py`, `backend/flows/graph.py`; graph executor with Run/Step persistence in the State Store and message/webhook/cron/Event Bus triggers (E3-S2); `GET/POST` routes in `backend/api/routers/flows.py` |
| Checkpointing, retries, deterministic replay | `default` | `backend/flows/checkpoint.py` (E3-S3); guarded loops (rework paths) are a first-class graph construct, not failure-specific classification |
| Human-in-the-loop pause/resume | `default` | `backend/flows/human.py` + `backend/flows/pause.py` (`FlowHumanService`, `FlowHumanError`) (E3-S4) |
| Composite nodes (sub-flow, map/reduce) | `default` | `backend/flows/composite.py` (E3-S5) |
| Visual flow editor (base) | `default` | Delivered alongside E10 via E10-S3 + `frontend/app/flows/`, `frontend/lib/flow/` (E3-S6) |

---

## Reasoning (v2)

Delivered by v2 epic E4 (Reasoning), Done 4/4. See
[`docs/v2_platform/phases/e4_reasoning.md`](v2_platform/phases/e4_reasoning.md).

| Feature | Status | Notes |
|---------|--------|-------|
| Reasoning strategy contract + Engine + registry | `default` | `backend/reasoning/`; five reference strategies with policy-driven selection and fallback (RFC-003/ADR-007), consumed by E11-S3 reasoning budgets (`backend/quotas/reasoning_budget.py`) |

---

## Routing, Selection & Evaluation (v2)

Delivered by v2 epic E5 (Routing / Selection / Evaluation), Done 4/4. See
[`docs/v2_platform/phases/e5_routing_selection_evaluation.md`](v2_platform/phases/e5_routing_selection_evaluation.md).

| Feature | Status | Notes |
|---------|--------|-------|
| Policy-driven Router/Selector | `default` | `backend/routing/{router,selector,policy,feedback}.py`; `backend/api/routers/routing.py`; capability matching, cost policy, and evaluation feedback — the successor to the v1 `SupervisorPolicy` stub above. **Not** wired into the v1 `POST /chat/dynamic` endpoint, which still routes exclusively through the LangGraph-based `orchestrator.graphs.build_graph_for_run_type` (see "Supervisor / feedback loop" above) |
| Evaluation Service | `default` | `backend/evals/{service,runner,spec,contract,results,dataset_loader,expressions}.py`; `backend/api/routers/evals.py`; consumed by E7-S3 (retrieval eval) and E12-S3 (agent evals) |

---

## Repository Intelligence

| Feature | Status | Notes |
|---------|--------|-------|
| File inventory + ranked candidate retrieval | `default` | `GET /repository/context`; `backend/repository/intelligence.py` |
| Lexical symbol extraction (regex) | `default` | `backend/repository/providers/lexical_provider.py`; `GET /repository/symbols` with `AUTODEV_REPO_PROVIDER` unset |
| tree-sitter symbol extraction | `optional` | `AUTODEV_REPO_PROVIDER=treesitter`; `backend/repository/providers/treesitter_provider.py` performs real AST-based extraction for Python via the vendored `tree-sitter-python` grammar (E7-S1), degrading gracefully to the lexical provider for unregistered languages or if `tree_sitter` is absent; scoped to Python only, other languages still delegate |
| Semantic retrieval (pgvector embeddings) | `optional` | `backend/repository/embeddings/pgvector_store.py`; PostgreSQL + pgvector query path used by the hybrid retriever below (E7-S2/S3) |
| Hybrid retrieval (lexical + vector, Reciprocal Rank Fusion) | `optional` | `backend/repository/retrieval/retriever.py` + `backend/repository/retrieval/fusion.py`; combines PostgreSQL FTS and pgvector results via RRF with per-result score/source attribution and token-budget truncation (E7-S3-T3/T4) |
| Full-text search (PostgreSQL FTS / ripgrep) | `optional` | `backend/repository/retrieval/lexical.py`; `to_tsvector`/`plainto_tsquery`/`ts_rank` over a GIN index (E7-S3-T1); PostgreSQL only, no ripgrep-based fallback |
| Repository metadata graph (symbols, edges) | `planned` | No dedicated symbol/dependency graph module found under `backend/repository/`; tracked in roadmap releases 0.3 / 1.0 |

---

## Patch Pipeline

| Feature | Status | Notes |
|---------|--------|-------|
| Patch generation (unified diff) | `default` | `backend/patches/engine.py`; `POST /patches/generate`; stdlib `difflib`, no external deps |
| Patch application (dry-run) | `default` | `apply_patch()` dry-runs by default; rejects path traversal outside root |
| Patch application (real write) | `optional` | `AUTODEV_ENABLE_PATCH_APPLY=1`; writes files only when flag is set |
| Patch persistence / versioning | `planned` | No durable patch rows or version history. `backend/api/routers/patches_review_v2.py` (E16-S3) adds a session-scoped review queue on top of the patch engine, but its own docstring states this is an in-process, non-durable module-level registry "until a durable store is warranted by a future story"; legacy `execute_plan()` still stores no patch rows |
| Orchestrator→patch integration | `default` | The legacy `execute_plan()` path (`backend/orchestrator/service.py`) still doesn't call `apply_patch()`, but it has been superseded by two real integrations: `backend/execution/runner.py`'s `PatchRunner` + `backend/execution/executor.py` dispatch `create_file`/`edit_file`/`apply_patch` actions through the E0 patch engine as part of E14's governed execution pipeline, and `backend/api/routers/patches_review_v2.py` applies reviewed patches via the same engine (E16-S3) |

---

## Validation / Sandbox

| Feature | Status | Notes |
|---------|--------|-------|
| Validation sandbox (Docker or local subprocess) | `optional` | `AUTODEV_ENABLE_SANDBOX=1`; `backend/validation/sandbox.py`; prefers hardened Docker (`--network=none`, non-root, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, CPU/memory/pids limits); fails closed without Docker unless `AUTODEV_SANDBOX_ALLOW_LOCAL=1` is also set; command allowlist enforced by basename |
| Executable validation pipeline | `optional` | Same flag as above; returns real exit codes and captured output when enabled |
| Validation skipped by default | `default` | Returns `skipped=true, backend="disabled"` unless flag is set |
| Failure classification / rework loop | `planned` | Tracked as Unit 29 in `docs/archive/v1/mvp_refactor_plan.md` |
| Isolated execution environment — Beta slice (pluggable environment abstraction) | `default` | E32 is Done (4/4 stories, 2026-08-18); `backend/environments/{contracts,manager,backends}.py` implement the provision → execute → collect evidence → teardown lifecycle behind a pluggable backend, consumed by `backend/execution/runner.py`; `docs/v2_platform/phases/e32_isolated_execution_beta.md` |

---

## Plan Approval Workflow

| Feature | Status | Notes |
|---------|--------|-------|
| Plan store | `default` | `backend/plans/store.py`; `plan_documents` table; approve/reject persisted; dual-backend via `SQLitePlanStore`/`PostgresPlanStore`. Per-step approval state is separate and **SQLite-only** (`backend/plans/step_state.py`) — E55 |
| Plan approval API | `default` | `GET/PUT /plans/{id}`, `POST /plans/{id}/approve`, `POST /plans/{id}/reject` |
| Approval gates blocking execution | `default` | Legacy `execute_plan()` still doesn't check plan status, but E14's governed execution pipeline gates on it: `backend/execution/executor.py` only skips the policy evaluator for an action whose id is in `pre_approved_action_ids` ("a human already explicitly approved this action"), backed by `backend/execution/policy.py` / `decisions.py` (E14-S3) |
| Plan auto-persisted from orchestrator | `planned` | `create_plan()` (`backend/orchestrator/service.py`) still writes to the session store only, not `PlanStore`; tracked as Unit 23 |

---

## Observability

| Feature | Status | Notes |
|---------|--------|-------|
| Request-ID tracing middleware | `default` | Attached via router loader `attach(app)` hook; `backend/observability/` |
| OpenTelemetry traces | `default` | `autodev.run`/`autodev.run.step.*`/`autodev.dependency.*`/`autodev.decision.*`/`autodev.model.call`/`http.server *` spans; `opentelemetry` is a hard dependency in `requirements.txt` (E11-S1) |
| OpenTelemetry metrics | `default` | Run/step/model/decision/queue/worker histograms and counters; `GET /metrics` (Prometheus text, in-process) plus the OTel path scraped from `otel-collector:9464` |
| Structured JSON logs | `default` | One JSON object per line, correlated by `run_id`/`trace_id`, redacted by `TelemetryRedactionFilter`; `docs/ops/observability.md` |
| Configurable sampling | `default` | `OTEL_TRACES_SAMPLER`/`OTEL_TRACES_SAMPLER_ARG`; defaults to `parentbased_traceidratio` at `1.0` |
| Configurable signal retention | `default` | `AUTODEV_OBSERVABILITY_TRACE_RETENTION`/`_METRIC_RETENTION`/`_LOG_RETENTION`, operator-set per backend |
| Self-hosted Grafana dashboard | `default` | `make observability-up`; ten-panel `autodev-overview` dashboard provisioned automatically |
| Emergency rollback | `default` | `OTEL_ENABLED=false` falls back to no-op providers with zero Collector dependency |
| Structured execution / action trace | `default` | E14-S1 (RFC-009) emits structured `execution.action.started`/`.completed`/`.failed` and `execution.policy.allowed`/`.denied` events per action (`backend/events/catalog.py`), alongside the `autodev.run.step.*`/`autodev.decision.*` OTel spans above; both are durably persisted and replayable via the E8-S2 Event Store's `EventStore.reconstruct_run()` |
| Alert delivery + operational runbooks | `default` | Alertmanager under the `observability` Compose profile (`infrastructure/observability/alertmanager.yml`, `prometheus-rules.yml`); five runbooks in `docs/v2_platform/runbooks/` (E11-S4, E35-S3) |

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
| Secret store & credential governance (encrypted at rest, redaction, scoped injection) | `default` | E33 Done (3/3 stories); `backend/secret_store/{store,crypto,redaction,service,contracts}.py` (durable tenant-scoped secret-version store, write-only ciphertext, `resolve_latest_active()` as the sole read path), `backend/security/secrets.py`, `backend/api/routers/secrets_v2.py` (E33-S1, ADR-014) |

---

## Multi-tenancy, RBAC & Quotas

Delivered mainly by E8-S1 (scoped tenancy), E11-S2 (RBAC), and E11-S3
(multi-tenant quotas/budgets) — all Done.

| Feature | Status | Notes |
|---------|--------|-------|
| Multi-tenant row-level isolation (PostgreSQL RLS) | `optional` | Mandatory `tenant_id` scoping on every `SessionRepository`/`RunRepository`/`MessageRepository`/`PlanRepository`/`EvalResultRepository`/`ScoreSnapshotRepository` method; `PostgresStore`/`PostgresPlanStore` additionally enforce Postgres Row-Level Security via `set_postgres_tenant()` (`backend/persistence/postgres_adapter.py`); ADR-010; requires the PostgreSQL backend. **Scope (verified 2026-08-21):** RLS covers the 11 core/plan/code tables only; the 13 domain tables (quotas, secrets, execution policy, environments, plan step state) have no RLS and rely on application-level `WHERE` clauses — E50-S4 |
| Global RBAC + authentication enforcement | `default` | `backend/api/authorization.py`; every `/v2` route must declare `@public_endpoint` or `@requires_scope(...)`, enforced as a single app-level FastAPI dependency ahead of all matched routes including plugin routers (E11-S2 Task 3) |
| Tenant quota / run budget policy | `default` | `backend/quotas/{contracts,service}.py` (`TenantQuotaPolicy`, `RunBudgetLimits`, integer micro-USD amounts); `GET/PUT /v2/quotas/*` (`backend/api/routers/quotas_v2.py`); `QuotaExceededError` enforced on `POST /chat/dynamic` and other run-creating routes (E11-S3, ADR-019) |

---

## MCP Interoperability

Delivered by E9-S4 (part of the Done E9 — APIs, Events & MCP epic).

| Feature | Status | Notes |
|---------|--------|-------|
| MCP server (expose platform skills as MCP tools) | `optional` | `backend/mcp/server.py` (`initialize`, `tools/list`, `tools/call`); routes every call through `SkillInvocationBroker` for permission/validation/timeout reuse; only skills allowlisted via `AUTODEV_MCP_EXPOSED_SKILLS` are exposed (empty by default) (E9-S4-T1/T3) |
| MCP client (consume external MCP servers as agent tools) | `optional` | `backend/mcp/client.py`; JSON-RPC 2.0 without the `mcp` pip package — `McpStdioClient` (subprocess stdio) and `McpHttpClient` (optional `httpx`) transports (E9-S4-T2) |

---

## Skills Subsystem

| Feature | Status | Notes |
|---------|--------|-------|
| Skills registry + auto-discovery | `default` | `backend/skills/registry.py`; `GET /skills`, `GET /skills/{name}`, `POST /skills/{name}/invoke` |
| Built-in skills | `default` | `summarize_diff`, `extract_symbols_lexical`, `render_checklist`; deterministic, no LLM needed |
| Skills CLI | `default` | `autodev skills list / invoke` |

### Skills v2 (E6, Done 5/5)

| Feature | Status | Notes |
|---------|--------|-------|
| `skill.yaml` manifest + v2 registry | `default` | `backend/skills/manifest.py` (parse/validate, mirrors `backend/plugins/manifest.py`'s shape), `backend/skills/registry_v2.py`; example manifests at `examples/plugins/skill-apply-patch/skill.yaml`, `examples/plugins/skill-summarize-llm/skill.yaml` |
| Least-privilege skill invocation broker | `default` | `backend/skills/invoker.py` (`SkillInvocationBroker`); permission enforcement, input/output validation, timeout budgets |
| Skill composition | `default` | `backend/skills/composition.py` |

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
| SSE run stream endpoint | `default` | `GET /v2/runs/{run_id}/events/stream` (`backend/api/routers/runs_stream_v2.py`, E9-S2) with backlog, resume and heartbeat. No numeric start-latency assertion exists — an open v2.0-beta gate criterion. The v1 `GET /sessions/{id}/runs/{run_id}/stream` shape was never built. |
| Real-time streaming UI | `default` | `frontend/components/RunEventStream.tsx`, `frontend/components/chat/useRunTimeline.ts` (E17-S1) |

---

## Frontend

| Feature | Status | Notes |
|---------|--------|-------|
| Next.js 14 App Router UI | `default` | Six pages: `/` (chat), `/config`, `/agents`, `/plans`, `/skills`, `/patches` |
| Themed styling via design tokens | `default` | E15-S1 design tokens v2 + `frontend/styles/globals.css`; both light and dark themes ship. `frontend/app/layout.tsx` sets `defaultTheme="light"` with `enableSystem={false}`, switchable via the toggle row below |
| Tailwind CSS + shadcn/ui | `default` | Unit 11 landed: `tailwind.config.ts`, `ThemeProvider.tsx` (next-themes) wraps every page, one shadcn primitive (`components/ui/button.tsx`) — **foundation/shell only**: zero pages or components import Tailwind utility classes or `Button` yet; all six pages still render via bespoke `globals.css` classNames. Adoption tracked as Units 12–18 |
| Plan approval UI (interactive) | `default` | Step-level approval gates — `frontend/components/plans/ExecuteApprovedFooter.tsx`, `frontend/components/execution/ActionApprovalPanel.tsx` (E16-S2, E17-S2) |
| Diff viewer | `default` | `frontend/components/patches/PatchDiffView.tsx` (E17-S3) |
| Run history panel | `planned` | `RunHistoryPanel.tsx` exists but is never rendered; tracked as Unit 16 |
| Observability dashboard | `planned` | Tracked as Unit 17 |
| Light/dark toggle | `default` | `frontend/components/ThemeToggle.tsx` switches `next-themes` between light/dark, rendered in `frontend/components/shell/SidebarRail.tsx`; `frontend/app/layout.tsx` sets `defaultTheme="light"` (E15-S1) |

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
| Kubernetes deployment | `planned` | `infrastructure/terraform/main.tf` is a placeholder; tracked in roadmap release 1.0 |
| Global install & upgrade (`autodev` CLI + self-host bundle) | `default` | E34 Done (3/3 stories); console-script entry point (`autodev = "backend.cli:main"` in `backend/pyproject.toml`, E14-S7/E34-S1), `autodev upgrade` backs up then migrates the state store (`backend/cli.py`, E34-S3-T1), `scripts/verify_clean_install.sh`; `docs/execution/cli-install.md` |
| Beta readiness gates & evidence bundle | `default` | E35 Done (3/3 stories, complete 2026-08-19); expanded 12-criterion §18.9 v2.0-beta gate checklist with named evidence per criterion (`docs/v2_platform/progress.md`), `docs/v2_platform/beta_acceptance_flow.md` (E35-S2 rehearsal), open-decisions/risk registers and incident runbooks under `docs/v2_platform/runbooks/e35_*.md` (E35-S3) |

---

*Last updated: 2026-08-20, reconciling every `planned`/`stub` row against the
completed v2.0 Beta wave (E0–E12, E14–E18, E32–E35 all Done; only E13/GA and
the v2.1+ waves remain not started). Flipped rows with citable evidence to
`default`/`optional` (isolated execution E32, secret store E33, global
install E34, beta readiness gates E35, alert delivery + runbooks E11-S4,
pgvector/hybrid retrieval/FTS/tree-sitter E7, agent tool-use loop and
orchestrator→patch/approval-gate integration via E14's governed executor,
structured execution/action trace, SSE stream + real-time UI, plan-approval
UI, diff viewer, light/dark toggle); left `planned` where no landed code was
found (Anthropic provider, repository metadata graph, patch
persistence/versioning as a durable store, failure-classification/rework
loop, plan auto-persistence into `PlanStore`, run history panel,
observability dashboard, infra/docs CI validation, Kubernetes deployment)
and left the v1 Supervisor/feedback-loop `stub` row as-is (E5's
Router/Selector remains unwired into `POST /chat/dynamic`). Added new
sections for v2-only capabilities with no prior row: Orchestration Engine
(v2 Flows, E3), Reasoning (v2, E4), Routing/Selection/Evaluation (v2, E5),
Skills v2 (E6), Multi-tenancy/RBAC/Quotas (E8-S1, E11-S2/S3), and MCP
Interoperability (E9-S4).
Previous update 2026-07-17, adding the planned E32–E35 Beta-hardening rows
(isolated execution, secret store, global install, readiness gates).
Earlier update 2026-07-04, adding the Plugin System (v2, E1) and Agent Framework
(v2, E2) sections, correcting the PostgreSQL and typed-settings rows, and adding
the E0-S5/E1-S3 security rows. See `docs/v2_platform/progress.md` for the current
v2 story tracker and `git log` for full history.*
