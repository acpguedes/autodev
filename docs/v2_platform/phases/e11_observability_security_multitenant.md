# E11 — Observability, Security & Multi-tenant

**Wave:** Beta
**Status:** Complete · **Stories:** 4/4 complete
**Depends on:** E0, E8, E9-S1, E4
**Enables:** governs access, tenants, and quotas/budgets platform-wide; integrates backups (E8-S4); audit sink (additive) for E32 isolation records (environment profile, policy denials) and E33 secret audit events (create/rotate/revoke/resolve — references only, never values)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.7.5 (E11), §18.8, §18.9

## Objective

Instrument the platform with **OpenTelemetry**, implement **RBAC**, **tenant**
isolation, **quotas/budgets**, and operational **runbooks**.

## Key result

Every run/step/decision is traceable end to end; access is governed by mandatory RBAC
in production; tenants have quotas and budgets that fail closed.

## Stories

### E11-S1 — Observability (OpenTelemetry) — complete (2026-08-15)

Subtasks:
- `E11-S1-T1`: traces/metrics/logs correlated by `run_id`/`trace_id`. **Done.**
- `E11-S1-T2`: OTel exporters and latency/error/cost dashboards. **Done.**
- `E11-S1-T3`: configurable sampling and retention. **Done.**

| Item | Content |
| --- | --- |
| CF | Every step emits a trace/metric; end-to-end correlation; operational dashboards available |
| CNF | Acceptable instrumentation overhead; OTel conventions followed; no sensitive PII in logs |
| DoR | E0 (observability base) ready; OTel backend provisioned |
| DoD | End-to-end trace correlation verified; dashboards published; observability docs |
| Dependencies | E0 |
| Evidence | `docs/ops/observability.md`; `scripts/verify_observability_stack.py` (live stack check, all four backends healthy); `scripts/measure_observability_overhead.py` (instrumentation overhead ~2.6–2.8%, target <5%); ADR-017 |

### E11-S2 — RBAC and authentication — complete (2026-08-15)

Subtasks:
- `E11-S2-T1`: role/permission model and enforcement in the Control Plane API. **Done.**
- `E11-S2-T2`: authentication (tokens/sessions) and per-resource scopes. **Done.**
- `E11-S2-T3`: access and denial auditing. **Done.**

| Item | Content |
| --- | --- |
| CF | Role-based permissions enforced on every endpoint; access audit trail; per-resource scoping |
| CNF | RBAC mandatory in production; deny-by-default on failure |
| DoR | E9-S1 (API) ready; role matrix approved |
| DoD | Negative authorization tests; verifiable audit; RBAC docs |
| Dependencies | E9-S1 |
| Evidence | ADR-018 (`docs/v2_platform/decisions/ADR-018-control-plane-authentication-rbac-audit.md`); `docs/security.md`; `backend/tests/contract/test_control_plane_authorization.py` (every non-public Control Plane route declares a scope); `backend/tests/unit/auth/`, `backend/tests/integration/test_auth_api.py`, `backend/tests/integration/test_v2_api_contract.py` (OpenAPI auth metadata) |

Note: per-resource cross-tenant concealment (`AuthorizationRequirement.resource_parameter`/`conceal_cross_tenant`) was implemented as a mechanism in S2 and is now enforced against real data by E11-S3's tenant-persistence-boundaries work below.

### E11-S3 — Multi-tenant and quotas/budgets — complete (2026-08-17)

Subtasks:
- `E11-S3-T1`: per-tenant data isolation (integrates E8's RLS) and tenant context in the API. **Done.**
- `E11-S3-T2`: per-tenant quotas (concurrent runs, storage) and per-run budgets (tokens/cost/time/steps). **Done.**
- `E11-S3-T3`: budget enforcement in the Agent Runtime and Reasoning Engine. **Done.**

| Item | Content |
| --- | --- |
| CF | A tenant cannot access another tenant's data; quotas/budgets enforced and observable; overrun stops execution with consistent state |
| CNF | Safe default budgets that fail closed; per run/tenant token/cost measurement |
| DoR | E8 (tenancy) and E4 (reasoning budgets) ready |
| DoD | Isolation and budget-overrun tests; quota dashboard; docs |
| Dependencies | E8, E4, E11-S2 |
| Evidence | ADR-019 (`docs/v2_platform/decisions/ADR-019-multitenant-quotas-and-run-budgets.md`); `backend/quotas/` (durable policy/lease/reservation/usage store + service, ADR-019); `backend/tests/integration/tenancy/test_cross_tenant_isolation.py` (includes the chat-turns leak this story found and closed — `chat_v2.py` never resolved the authenticated tenant); `backend/tests/unit/orchestrator/test_orchestrator_quotas.py` (concurrent-run admission fails closed, lease always released); `backend/tests/unit/artifacts/test_artifact_pointers.py::TestPersistArtifactStorageQuota` (storage-byte denial and release); `backend/tests/unit/quotas/test_reasoning_budget.py` and `test_reasoning_selection.py::TestTenantBudgetEnforcement` (tenant budget narrows the Reasoning Engine's ceiling; monthly usage recorded without corrupting a completed run); `backend/tests/unit/api/test_quotas_api.py` (`/v2/quotas/usage`\|`policy`, tenant isolation, rate-limit 429); `autodev quotas get\|set` CLI; `backend/observability/quota_metrics.py` + `infrastructure/observability/grafana/dashboards/quotas.json` (quota dashboard) |

Scope note: full per-token LLM cost/usage accounting is enforced end to end wherever a run goes through the Reasoning Engine (E4) — the mediator narrows the tenant's budget and records real monthly usage after every run. The older LangGraph-based `OrchestratorService` agent pipeline (`handle_message`/`execute_plan`) does not yet instrument real per-call token/cost accounting (`flow.run.completed`'s `costUsd`/`tokens` fields are still hardcoded placeholders, pre-existing and unrelated to this story) — recording fabricated zero-usage against a tenant's monthly ceiling there would be dishonest telemetry, so it is deliberately not done. That runtime does get real, tested concurrent-run admission control (the same fail-closed lease mechanism), which is this story's Agent Runtime enforcement. Wiring real LLM cost accounting into that runtime is E14's job. Similarly, `respect_tenant_quota` on E5's cost-aware model selection (`backend/routing/{selector,contract,policy}.py`) remains parsed-but-unenforced — threading a tenant/remaining-budget argument through that whole selection call chain is a separate, larger change outside this story's boundary.

### E11-S4 — Execution security and runbooks — complete (2026-08-15)

Subtasks:
- `E11-S4-T1`: no-network-by-default sandbox and explicit plugin permissions. **Done.**
- `E11-S4-T2`: secret management and dependency/secret scanning. **Done.**
- `E11-S4-T3`: incident/restore runbooks and alerts. **Done.**

| Item | Content |
| --- | --- |
| CF | Execution and plugins run under least privilege; secrets protected; runbooks are executable |
| CNF | Sandbox with no network by default; secret scanning in CI; actionable alerts |
| DoR | E1 (plugin permissions) and a base Execution Sandbox available |
| DoD | Sandbox network-denial test; runbooks published; alerts configured |
| Dependencies | E1, E8-S4 |
| Evidence | ADR-020 (trusted-only in-process plugin boundary); `backend/tests/integration/test_sandbox_security_contract.py` (3/3 passed, zero skips, live Docker); `.trivyignore.yaml` + `scripts/validate_security_exceptions.py` (HIGH/CRITICAL vuln+license Trivy gate); `infrastructure/observability/alertmanager.yml` + `prometheus-rules.yml` `autodev-e11-s4-backup` group (`promtool`/`amtool` both SUCCESS, live-verified against a running Prometheus/Alertmanager); `docs/v2_platform/runbooks/e11_incident_response.md` |

## v1 precursor / starting point

- Request-ID tracing middleware and a Prometheus `GET /metrics` endpoint are already
  `default`; OpenTelemetry tracing is `optional` (only active when the package is
  importable) — this is a partial precursor to E11-S1, which should make it a
  first-class, always-on capability (built by E0-S3 and hardened here).
- There is no RBAC, no tenants, and no quotas/budgets today — E11-S2 and E11-S3 start
  from zero.
- The validation sandbox (`backend/validation/sandbox.py`, Docker or subprocess) is
  `optional` behind `AUTODEV_ENABLE_SANDBOX=1` and already enforces a command
  allowlist — a useful precursor for E11-S4's no-network-by-default execution
  sandbox, though it is not yet the default and has no formal runbook set.

## Epic exit checklist

- [x] All 4 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [x] Contract tests green for RBAC enforcement and tenant-scoped data access.
- [x] `docs/v2_platform/progress.md` updated.
- [x] Beta wave entry item "OpenTelemetry, RBAC, multi-tenant, quotas/budgets,
      runbooks" satisfied (§18.9).
