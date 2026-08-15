# E11 — Observability, Security & Multi-tenant

**Wave:** Beta
**Status:** In progress · **Stories:** 3/4 complete
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

Note: per-resource cross-tenant concealment (`AuthorizationRequirement.resource_parameter`/`conceal_cross_tenant`) is implemented as a mechanism but not yet enforced against real data — no domain object carries a `tenant_id` to compare against before E11-S3 lands. `backend/api/routers/context.py`'s `GET /v2/context/retrieve` still accepts a caller-supplied `tenant_id` query parameter with no check against the authenticated principal; closing that is E11-S3's job, not re-flagged here as an S2 gap.

### E11-S3 — Multi-tenant and quotas/budgets

Subtasks:
- `E11-S3-T1`: per-tenant data isolation (integrates E8's RLS) and tenant context in the API.
- `E11-S3-T2`: per-tenant quotas (concurrent runs, storage) and per-run budgets (tokens/cost/time/steps).
- `E11-S3-T3`: budget enforcement in the Agent Runtime and Reasoning Engine.

| Item | Content |
| --- | --- |
| CF | A tenant cannot access another tenant's data; quotas/budgets enforced and observable; overrun stops execution with consistent state |
| CNF | Safe default budgets that fail closed; per run/tenant token/cost measurement |
| DoR | E8 (tenancy) and E4 (reasoning budgets) ready |
| DoD | Isolation and budget-overrun tests; quota dashboard; docs |
| Dependencies | E8, E4, E11-S2 |

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

- [ ] All 4 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [ ] Contract tests green for RBAC enforcement and tenant-scoped data access.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Beta wave entry item "OpenTelemetry, RBAC, multi-tenant, quotas/budgets,
      runbooks" satisfied (§18.9).
