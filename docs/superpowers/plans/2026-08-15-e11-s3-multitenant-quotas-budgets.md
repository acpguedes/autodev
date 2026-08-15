# E11-S3 Multi-Tenant Quotas and Run Budgets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce tenant isolation, durable per-tenant quotas, and one composable run budget across orchestration, flows, agents, model calls, reasoning, artifacts, approvals, and events.

**Architecture:** The authenticated E11-S2 principal supplies the only authoritative tenant context. PostgreSQL combines explicit tenant predicates with forced row-level security; SQLite uses the same repository contracts with explicit predicates and parent joins. PostgreSQL or SQLite remains the durable quota and budget authority, while Redis may only accelerate reads. Atomic leases, reservations, settlements, and heartbeats prevent concurrent workers from overspending, and one run-scoped budget handle is narrowed—not replaced—by downstream components.

**Tech Stack:** FastAPI, Pydantic v2, PostgreSQL/SQLite, PostgreSQL RLS, optional Redis cache, Next.js 14, React 18, pytest, Vitest.

**Spec:** `docs/v2_platform/phases/e11_observability_security_multitenant.md` E11-S3 and `docs/architecture/v2_platform_reference.md` §16.2 and §18.7.5.

## Global Constraints

- Implement on `story/e11-s3-multitenant-quotas-budgets`, cut from the E11 epic branch after E11-S2 is merged.
- Reuse the E11-S2 `PrincipalV2`. A body, query parameter, or arbitrary header never selects a tenant; any transitional tenant value must equal `principal.tenant_id` or receive the repository's not-found response.
- Directly scope tenant-owned roots. Preserve E8 transitive child scoping when every operation joins a protected parent and PostgreSQL RLS proves isolation with `EXISTS`; add child `tenant_id` only when independently addressable or no mandatory protected-parent path exists.
- PostgreSQL policies use `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY`, and `current_setting('app.tenant_id', true)`. SQLite uses explicit predicates or mandatory tenant-scoped parent joins.
- PostgreSQL/SQLite is authoritative for policies, leases, reservations, usage, and budgets. Redis is an optional disposable cache only.
- Enforce finite concurrent-run, storage-byte, monthly-token, monthly-cost, and per-credential request-rate limits. Warn durably once per resource/window at 80%; deny atomically at exhaustion.
- Enforce per-run token, cost, wall-clock, and step limits. Store money as integer micro-USD. Charge known usage for every provider attempt, including failures and retries.
- Production fails closed for a missing quota policy, unknown model price, or unmetered provider result. Local mode receives explicit finite defaults: 4 concurrent runs, 1 GiB stored artifacts, 20 requests per second, 20,000,000 tokens and 100,000,000 micro-USD per UTC month; its default run budget preserves the existing ceilings of 2,000,000 tokens, 10,000,000 micro-USD, 3,600,000 ms, and 1,000 steps.
- Prometheus metrics must not label by tenant, subject, credential, run, or session. Tenant detail belongs in authorized APIs and durable events/traces.
- Do not add billing, invoices, plan catalogs, retention, purge jobs, or general FinOps/IAM functionality.
- Activate `.venv` before Python, tests, migrations, linters, or backend commands.
- Run targeted checks while implementing; after the final change run required story gates and `graphify update .` once.

---

### Task 1: Freeze ADR-019 and Typed Quota/Budget Contracts

**Files:**

- Create: `docs/v2_platform/decisions/ADR-019-multitenant-quotas-and-run-budgets.md`
- Create: `backend/quotas/__init__.py`
- Create: `backend/quotas/contracts.py`
- Create: `backend/tests/unit/quotas/test_contracts.py`
- Modify: `docs/v2_platform/decisions/README.md`
- Modify: `backend/config/settings.py`
- Test: `backend/tests/unit/config/test_settings.py`

**Completion criteria:** ADR-019 makes isolation/accounting semantics reviewable before storage work; typed contracts reject invalid policy and never use floating-point currency.

- [ ] **Write RED tests.** Cover finite positive limits, UTC monthly windows, 8,000-basis-point warnings, micro-USD rounding, componentwise budget narrowing, invalid limits, production without explicit policy, and finite local defaults.

```python
def test_child_budget_can_only_narrow_parent() -> None:
    parent = RunBudgetLimits(
        max_tokens=10_000,
        max_cost_microusd=2_000_000,
        max_wall_clock_ms=600_000,
        max_steps=100,
    )
    assert narrow_budget(
        parent,
        RunBudgetLimits(max_tokens=2_000, max_steps=20),
    ) == RunBudgetLimits(
        max_tokens=2_000,
        max_cost_microusd=2_000_000,
        max_wall_clock_ms=600_000,
        max_steps=20,
    )
```

- [ ] **Run RED.**

```bash
source .venv/bin/activate && pytest -q backend/tests/unit/quotas/test_contracts.py backend/tests/unit/config/test_settings.py
```

- [ ] **Write ADR-019.** Decide: principal-authoritative tenant context; direct roots plus provable transitive child scoping; PostgreSQL forced RLS/SQLite predicates; database authority/optional Redis; UTC calendar-month windows; fixed one-second request windows; 90-second run leases with 30-second heartbeat; reserve before external work and settle actual usage; integer micro-USD; the exact local defaults from Global Constraints; production fail-closed gaps; once-only 80% warnings; no identity labels in Prometheus.

- [ ] **Implement contracts and settings.** Export `RunBudgetLimits(max_tokens, max_cost_microusd, max_wall_clock_ms, max_steps)`, `TenantQuotaPolicy(tenant_id, max_concurrent_runs, max_storage_bytes, monthly_token_limit, monthly_cost_microusd, requests_per_second, default_run_budget, warning_ratio_basis_points, version)`, `UsageDelta`, `BudgetSnapshot`, resource/denial enums, `usd_to_micros(Decimal)`, `narrow_budget(parent, requested)`, and UTC-window helpers. Add local-default, lease, heartbeat, and production-strictness settings.

- [ ] **Run GREEN and verify exports.**

```bash
source .venv/bin/activate && pytest -q backend/tests/unit/quotas/test_contracts.py backend/tests/unit/config/test_settings.py
source .venv/bin/activate && python -c "from backend.quotas import RunBudgetLimits, TenantQuotaPolicy; print(RunBudgetLimits, TenantQuotaPolicy)"
```

- [ ] **Commit.**

```bash
git add docs/v2_platform/decisions/ADR-019-multitenant-quotas-and-run-budgets.md docs/v2_platform/decisions/README.md backend/quotas backend/config/settings.py backend/tests/unit/quotas/test_contracts.py backend/tests/unit/config/test_settings.py
git commit -m "feat(e11-s3): define quota and budget contracts"
```

---

### Task 2: Propagate Principal Tenant Context and Close Isolation Gaps

**Files:**

- Create: `backend/quotas/migrations.py`
- Create: `backend/tests/integration/tenancy/test_cross_tenant_isolation.py`
- Create: `backend/tests/integration/tenancy/test_postgres_rls.py`
- Modify: `backend/auth/contracts.py`
- Modify: `backend/api/authorization.py`
- Modify: `backend/api/routers/orchestration.py`
- Modify: `backend/api/routers/sessions_v2.py`
- Modify: `backend/api/routers/flows.py`
- Modify: `backend/api/routers/runs_stream_v2.py`
- Modify: `backend/api/routers/plan_approval_v2.py`
- Modify: `backend/api/routers/patches_review_v2.py`
- Modify: `backend/persistence/database.py`
- Modify: `backend/persistence/tenancy.py`
- Modify: `backend/persistence/sqlite_adapter.py`
- Modify: `backend/persistence/postgres_adapter.py`
- Modify: `backend/orchestrator/service.py`
- Modify: `backend/flows/state.py`
- Modify: `backend/flows/records.py`
- Modify: `backend/flows/schema_sql.py`
- Modify: `backend/events/records.py`
- Modify: `backend/events/store.py`
- Modify: `backend/artifacts/pointers.py`
- Modify: `backend/artifacts/store.py`
- Modify: `backend/plans/step_state.py`
- Modify: `backend/plans/store.py`
- Test: `backend/tests/unit/orchestrator/test_orchestrator.py`
- Test: `backend/tests/unit/flows/test_flows_engine.py`
- Test: `backend/tests/unit/events/test_event_store.py`
- Test: `backend/tests/unit/artifacts/test_artifact_pointers.py`
- Test: `backend/tests/unit/plans/test_plan_approval_v2.py`
- Test: `backend/tests/unit/patches/test_patches_review_v2.py`

**Completion criteria:** Every tenant-owned root and independently addressable row is isolated in both databases; E8 child scoping stays transitive only when repository operations and RLS enforce the parent relationship.

- [ ] **Write RED isolation tests.** Create colliding identifiers under two tenants where schemas allow. Assert list/get/update/approve/cancel/download/review cannot observe or mutate the other tenant. PostgreSQL tests set `app.tenant_id` using the application role and prove direct and parent-derived RLS; SQLite tests prove predicates and parent joins.

- [ ] **Run RED once and map failures to boundaries.**

```bash
source .venv/bin/activate && pytest -q backend/tests/integration/tenancy backend/tests/unit/orchestrator/test_orchestrator.py backend/tests/unit/flows/test_flows_engine.py backend/tests/unit/events/test_event_store.py backend/tests/unit/artifacts/test_artifact_pointers.py backend/tests/unit/plans/test_plan_approval_v2.py backend/tests/unit/patches/test_patches_review_v2.py
```

- [ ] **Thread explicit tenant context.** Route handlers use E11-S2 `Principal` and pass `principal.tenant_id`; remove request-selected defaults. Make tenant keyword-only in orchestration and store methods, including `create_plan`, `handle_message`, `get_plan`, `list_sessions`, `get_session`, `list_runs`, `build_execution_plan`, `execute_plan`, `FlowRunStore.get_run`, `EventStore.list_events`, and approval/review operations.

- [ ] **Apply the smallest durable schema changes.** Add direct `tenant_id` plus indexes to roots and independently addressable rows. Keep run/flow-step-like children transitively scoped only when every method joins the parent. Move the standalone SQLite approval store and in-memory patch review state behind configured persistence so PostgreSQL has no hidden local authority.

- [ ] **Install forced PostgreSQL RLS.** Set validated tenant transaction-locally with `set_config('app.tenant_id', tenant_id, true)`. Direct policies compare root tenant; transitive policies use `EXISTS` on the protected parent. Missing setting never falls back to unscoped access. Migration rollback removes only new policies/columns/indexes.

- [ ] **Run GREEN and inspect migration checks.**

```bash
source .venv/bin/activate && pytest -q backend/tests/integration/tenancy backend/tests/unit/orchestrator/test_orchestrator.py backend/tests/unit/flows/test_flows_engine.py backend/tests/unit/events/test_event_store.py backend/tests/unit/artifacts/test_artifact_pointers.py backend/tests/unit/plans/test_plan_approval_v2.py backend/tests/unit/patches/test_patches_review_v2.py
source .venv/bin/activate && python -m backend.quotas.migrations --check
```

- [ ] **Commit.**

```bash
git add backend/auth/contracts.py backend/api backend/persistence backend/orchestrator/service.py backend/flows backend/events backend/artifacts backend/plans backend/quotas/migrations.py backend/tests/integration/tenancy backend/tests/unit/orchestrator/test_orchestrator.py backend/tests/unit/flows/test_flows_engine.py backend/tests/unit/events/test_event_store.py backend/tests/unit/artifacts/test_artifact_pointers.py backend/tests/unit/plans/test_plan_approval_v2.py backend/tests/unit/patches/test_patches_review_v2.py
git commit -m "feat(e11-s3): enforce tenant persistence boundaries"
```

---

### Task 3: Add the Durable Tenant Quota Store, Service, API, and CLI

**Files:**

- Create: `backend/quotas/store.py`
- Create: `backend/quotas/service.py`
- Create: `backend/quotas/rate_limit.py`
- Create: `backend/api/routers/quotas_v2.py`
- Create: `backend/cli_plugins/quotas.py`
- Create: `backend/tests/unit/quotas/test_store.py`
- Create: `backend/tests/unit/quotas/test_service.py`
- Create: `backend/tests/unit/quotas/test_rate_limit.py`
- Create: `backend/tests/unit/api/test_quotas_v2.py`
- Create: `backend/tests/integration/quotas/test_quota_atomicity.py`
- Modify: `backend/api/main.py`
- Modify: `backend/api/authorization.py`
- Modify: `backend/artifacts/store.py`
- Modify: `backend/events/catalog.py`
- Modify: `backend/events/records.py`
- Modify: `backend/events/store.py`
- Modify: `backend/cli.py`

**Completion criteria:** Administrators can manage/reconcile durable policy; request, storage, monthly-usage, and concurrent-run limits are atomic across processes and remain correct without Redis.

- [ ] **Write RED tests.** Cover policy compare-and-swap, missing production policy, local bootstrap policy, two database connections racing for the final lease/request slot/storage reservation, expired-lease reclamation, reserve/commit/release storage, UTC rollover, monthly token/cost exhaustion, exactly one 80% warning, authorized reads, owner/admin writes, and absence of an API tenant selector.

- [ ] **Run RED.**

```bash
source .venv/bin/activate && pytest -q backend/tests/unit/quotas backend/tests/unit/api/test_quotas_v2.py backend/tests/integration/quotas/test_quota_atomicity.py
```

- [ ] **Create durable schema/store.** Add `tenant_quota_policies`, `tenant_usage_windows`, `run_leases`, `storage_reservations`, `request_rate_buckets`, and `quota_warning_markers`. Use row locking/conditional updates in PostgreSQL and immediate transactions/conditional updates in SQLite. Idempotency keys make retries safe. `QuotaStore` must expose policy get/upsert, run-lease acquire/heartbeat/release, storage reserve/commit/release, request-slot consumption, monthly-usage recording, usage snapshot, and reconciliation.

- [ ] **Implement enforcement.** `QuotaService` resolves local defaults or production policy and owns warning/exceeded durable events. Apply per-credential rate limiting after E11-S2 authentication; public health/docs remain outside it. Reserve artifact bytes before a write, settle actual size on success, and release on failure. Optional Redis caches policy/snapshots only; admission always commits in the database.

- [ ] **Expose governed operations.** Add authorized `GET /v2/quotas/current` and `GET /v2/quotas/usage`; owner/admin `PUT /v2/quotas/current` uses `expected_version`. Add `autodev quotas show|set|reconcile`. Return stable `429`/`409` payloads with resource, limit, used, reserved, window end, and retry delay without cross-tenant values.

- [ ] **Run GREEN.**

```bash
source .venv/bin/activate && pytest -q backend/tests/unit/quotas backend/tests/unit/api/test_quotas_v2.py backend/tests/integration/quotas/test_quota_atomicity.py backend/tests/unit/artifacts
```

- [ ] **Commit.**

```bash
git add backend/quotas backend/api/routers/quotas_v2.py backend/api/main.py backend/api/authorization.py backend/artifacts/store.py backend/events backend/cli.py backend/cli_plugins/quotas.py backend/tests/unit/quotas backend/tests/unit/api/test_quotas_v2.py backend/tests/integration/quotas backend/tests/unit/artifacts
git commit -m "feat(e11-s3): enforce durable tenant quotas"
```

---

### Task 4: Implement Atomic Run Admission and the Shared Budget Handle

**Files:**

- Create: `backend/quotas/budgets.py`
- Create: `backend/tests/unit/quotas/test_budgets.py`
- Create: `backend/tests/integration/quotas/test_budget_atomicity.py`
- Modify: `backend/quotas/store.py`
- Modify: `backend/quotas/service.py`
- Modify: `backend/quotas/migrations.py`
- Modify: `backend/orchestrator/service.py`
- Modify: `backend/flows/model.py`
- Modify: `backend/flows/budgets.py`
- Modify: `backend/flows/engine.py`
- Modify: `backend/agents/contracts.py`
- Modify: `backend/reasoning/contract.py`
- Test: `backend/tests/unit/orchestrator/test_orchestrator.py`
- Test: `backend/tests/unit/flows/test_flows_engine.py`

**Completion criteria:** Admission atomically acquires one concurrency lease and one durable ledger; retries/resumes reuse them, and downstream budgets can only narrow remaining allowance.

- [ ] **Write RED tests.** Cover lease-plus-ledger atomicity, final-slot races, setup rollback, idempotent resume, expired recovery, heartbeat, step/wall exhaustion, componentwise narrowing, reservation-overrun denial, idempotent settlement, and one canonical `run.budget_exhausted` event.

- [ ] **Run RED.**

```bash
source .venv/bin/activate && pytest -q backend/tests/unit/quotas/test_budgets.py backend/tests/integration/quotas/test_budget_atomicity.py backend/tests/unit/orchestrator/test_orchestrator.py backend/tests/unit/flows/test_flows_engine.py
```

- [ ] **Add durable ledgers.** Add `run_budget_ledgers` and `budget_reservations`, keyed by tenant/run and tenant/run/idempotency key. Store limits; consumed/reserved tokens and micro-USD; steps; start/deadline; terminal reason; version; heartbeat. One transaction acquires the lease, computes the effective budget, and creates or resumes the ledger.

- [ ] **Implement `RunBudgetHandle`.** Expose atomic `snapshot()`, `remaining()`, `checkpoint(steps=0)`, `consume(delta, idempotency_key)`, `reserve_model_call(estimate, idempotency_key)`, `settle_model_call(reservation_id, actual)`, `heartbeat()`, and `finish(outcome)`. Effective limits are the componentwise minimum of tenant default, caller request, flow, agent, reasoning, and model caps. Normal callers only omit or tighten; quota administration alone raises defaults.

- [ ] **Wire orchestration/flow admission.** The orchestrator calls `QuotaService.admit_run` before scheduling and passes the handle plus absolute monotonic deadline in `FlowExecutionContext`. Flow boundaries call `checkpoint(steps=1)`. One `finally` owner calls `finish`; setup failure rolls back ledger and lease.

- [ ] **Run GREEN.**

```bash
source .venv/bin/activate && pytest -q backend/tests/unit/quotas/test_budgets.py backend/tests/integration/quotas/test_budget_atomicity.py backend/tests/unit/orchestrator/test_orchestrator.py backend/tests/unit/flows/test_flows_engine.py
```

- [ ] **Commit.**

```bash
git add backend/quotas backend/orchestrator/service.py backend/flows backend/agents/contracts.py backend/reasoning/contract.py backend/tests/unit/quotas/test_budgets.py backend/tests/integration/quotas/test_budget_atomicity.py backend/tests/unit/orchestrator/test_orchestrator.py backend/tests/unit/flows/test_flows_engine.py
git commit -m "feat(e11-s3): add atomic run budget admission"
```

---

### Task 5: Enforce the Shared Budget Across Runtimes

**Files:**

- Modify: `backend/agents/runtime.py`
- Modify: `backend/agents/contracts.py`
- Modify: `backend/llm/gateway.py`
- Modify: `backend/llm/contracts.py`
- Modify: `backend/llm/gateway_state.py`
- Modify: `backend/reasoning/engine.py`
- Modify: `backend/reasoning/service.py`
- Modify: `backend/reasoning/agent_binding.py`
- Modify: `backend/flows/engine.py`
- Modify: `backend/events/catalog.py`
- Modify: `backend/events/records.py`
- Modify: `backend/events/store.py`
- Test: `backend/tests/unit/agents/test_agents_runtime.py`
- Test: `backend/tests/unit/llm/test_model_gateway.py`
- Create: `backend/tests/unit/reasoning/test_budget_enforcement.py`
- Create: `backend/tests/integration/quotas/test_runtime_budget_enforcement.py`

**Completion criteria:** Every step, agent iteration, provider attempt/retry/stream, and reasoning node uses the same durable budget; no component resets deadlines or hides usage.

- [ ] **Write RED tests.** Prove pre-call wall/step checks; reserve-before-provider; settlement for success/failure/retry/stream; billing of failed attempts with usage; production denial for missing usage or price; cancellation settlement; reasoning degradation cannot reset its handle; repeated propagation yields one exhaustion event and consistent terminal error.

- [ ] **Run RED.**

```bash
source .venv/bin/activate && pytest -q backend/tests/unit/agents/test_agents_runtime.py backend/tests/unit/llm/test_model_gateway.py backend/tests/unit/reasoning/test_budget_enforcement.py backend/tests/integration/quotas/test_runtime_budget_enforcement.py
```

- [ ] **Make provider-attempt accounting explicit.** Add `ModelAttemptAccountant.reserve(estimate, attempt_id)`, `settle(reservation_id, actual)`, and `fail(reservation_id, actual_or_none)`. Estimate from input tokens, output cap, and governed price table; persist attempt ID before dispatch. Settle attempts independently so retries add usage. Local documented fallback estimates may handle unmetered results; production denies without governed usage and price.

- [ ] **Thread one handle.** `AgentRuntime` checkpoints each tool/model iteration and honors the absolute deadline. `ModelGateway` reserves each complete/stream attempt and settles in `finally`. Reasoning engine/service/bindings receive a narrowed view of the same handle and final-check before return. Flow passes the handle rather than reconstructing limits.

- [ ] **Normalize exhaustion.** One typed domain exception carries dimension, used, reserved, limit, and retryability. API/flow/agent layers preserve its code. The ledger compare-and-set that first exhausts also writes one durable outbox/event record. Metrics aggregate only by low-cardinality dimension/outcome.

- [ ] **Run GREEN.**

```bash
source .venv/bin/activate && pytest -q backend/tests/unit/agents/test_agents_runtime.py backend/tests/unit/llm/test_model_gateway.py backend/tests/unit/reasoning/test_budget_enforcement.py backend/tests/integration/quotas/test_runtime_budget_enforcement.py
```

- [ ] **Commit.**

```bash
git add backend/agents backend/llm backend/reasoning backend/flows/engine.py backend/events backend/tests/unit/agents/test_agents_runtime.py backend/tests/unit/llm/test_model_gateway.py backend/tests/unit/reasoning/test_budget_enforcement.py backend/tests/integration/quotas/test_runtime_budget_enforcement.py
git commit -m "feat(e11-s3): enforce budgets across runtimes"
```

---

### Task 6: Surface Authorized Usage, Document Operations, and Run Gates

**Files:**

- Create: `frontend/components/quotas/QuotaUsagePanel.tsx`
- Create: `frontend/components/quotas/RunBudgetPanel.tsx`
- Create: `frontend/components/quotas/__tests__/QuotaUsagePanel.test.tsx`
- Create: `frontend/components/quotas/__tests__/RunBudgetPanel.test.tsx`
- Create: `frontend/lib/api_quotas_v2.ts`
- Create: `frontend/app/quotas/page.tsx`
- Create: `docs/operations/quota-reconciliation.md`
- Modify: `frontend/lib/api_v2.ts`
- Modify: `frontend/app/sessions/[sessionId]/page.tsx`
- Modify: `frontend/components/shell/navModel.ts`
- Modify: `scripts/generate_openapi_v2.py`
- Modify: `docs/api/openapi_v2.json`
- Modify: `backend/observability/metrics.py`
- Modify: `backend/tests/integration/test_v2_api_contract.py`
- Modify: `backend/tests/unit/observability/test_observability.py`
- Modify: `README.md`
- Modify: `DESCRIPTION.md`
- Modify: `docs/architecture/v2_platform_reference.md`
- Modify: `docs/v2_platform/phases/e11_observability_security_multitenant.md`
- Modify: `docs/v2_platform/progress.md`
- Modify: `docs/roadmap.md`

**Completion criteria:** Authorized users see only their usage and run budget; operators have a reconciliation runbook; schemas/events/metrics are tested; required gates pass.

- [ ] **Write RED UI/OpenAPI/metrics tests.** Cover percentage/warning/exhausted states, UTC reset, micro-USD display, run remaining/consumed values, inaccessible data, and no tenant selector. Require stable schemas/errors. Reject metric label names `tenant`, `tenant_id`, `subject`, `credential`, `run_id`, and `session_id`.

- [ ] **Run RED.**

```bash
source .venv/bin/activate && pytest -q backend/tests/integration/test_v2_api_contract.py backend/tests/unit/observability/test_observability.py
cd frontend && npm test -- --run components/quotas
```

- [ ] **Implement authorized surfaces.** Add `QuotaUsageV2` and `RunBudgetUsageV2` client types. Render tenant usage on the new quota page and run budget on the existing session detail page from E11-S2-authenticated APIs. Show limits, used, reserved, remaining, warning, window/deadline. Never place a tenant selector or tenant ID in browser storage.

- [ ] **Finish docs.** Document finite local defaults, mandatory production policy, RLS and transitive-child invariant, request windows, UTC monthly windows, reservations/reconciliation, lease recovery, fail-closed metering, and stable events. The runbook uses `autodev quotas show|reconcile` and safe diagnostics; it contains no purge/retention procedure.

- [ ] **Run focused GREEN.**

```bash
source .venv/bin/activate && pytest -q backend/tests/integration/test_v2_api_contract.py backend/tests/unit/observability/test_observability.py
cd frontend && npm test -- --run components/quotas
```

- [ ] **Run final story gates once after the last change.** Diagnose captured output before any justified rerun.

```bash
source .venv/bin/activate && make check-backend
cd frontend && npm run lint && npm test -- --run && npm run build
source .venv/bin/activate && graphify update .
git status --short
```

- [ ] **Self-review.** Trace every E11-S3 criterion to tests; verify direct/provable transitive scoping, no request-selected tenant, forced PostgreSQL RLS, SQLite predicates/joins, atomic/idempotent accounting, non-authoritative Redis, all-attempt accounting, production fail-closed behavior, de-duplicated warnings/events, finite local defaults, low-cardinality metrics, and absence of retention/purge/billing/IAM expansion.

- [ ] **Commit.**

```bash
git add frontend scripts/generate_openapi_v2.py backend/observability/metrics.py backend/tests/integration/test_v2_api_contract.py backend/tests/unit/observability/test_observability.py docs README.md DESCRIPTION.md
git commit -m "docs(e11-s3): surface and operate tenant budgets"
```

## Handoff Checklist

- [ ] Story branch contains only E11-S3 changes and is based on the E11 epic branch with E11-S2 merged.
- [ ] ADR-019 is accepted and matches implementation.
- [ ] Targeted RED/GREEN evidence is retained.
- [ ] Backend and frontend gates plus `graphify update .` pass after the last source change.
- [ ] Follow `CONTRIBUTING.md`: merge story into epic, push, delete story branch; epic reaches `main` only through its PR.
