# E11 — Observability, Security & Multi-tenant

**Wave:** Beta
**Status:** Not started · **Stories:** 0/4 complete
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

### E11-S1 — Observability (OpenTelemetry)

Subtasks:
- `E11-S1-T1`: traces/metrics/logs correlated by `run_id`/`trace_id`.
- `E11-S1-T2`: OTel exporters and latency/error/cost dashboards.
- `E11-S1-T3`: configurable sampling and retention.

| Item | Content |
| --- | --- |
| CF | Every step emits a trace/metric; end-to-end correlation; operational dashboards available |
| CNF | Acceptable instrumentation overhead; OTel conventions followed; no sensitive PII in logs |
| DoR | E0 (observability base) ready; OTel backend provisioned |
| DoD | End-to-end trace correlation verified; dashboards published; observability docs |
| Dependencies | E0 |

### E11-S2 — RBAC and authentication

Subtasks:
- `E11-S2-T1`: role/permission model and enforcement in the Control Plane API.
- `E11-S2-T2`: authentication (tokens/sessions) and per-resource scopes.
- `E11-S2-T3`: access and denial auditing.

| Item | Content |
| --- | --- |
| CF | Role-based permissions enforced on every endpoint; access audit trail; per-resource scoping |
| CNF | RBAC mandatory in production; deny-by-default on failure |
| DoR | E9-S1 (API) ready; role matrix approved |
| DoD | Negative authorization tests; verifiable audit; RBAC docs |
| Dependencies | E9-S1 |

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

### E11-S4 — Execution security and runbooks

Subtasks:
- `E11-S4-T1`: no-network-by-default sandbox and explicit plugin permissions.
- `E11-S4-T2`: secret management and dependency/secret scanning.
- `E11-S4-T3`: incident/restore runbooks and alerts.

| Item | Content |
| --- | --- |
| CF | Execution and plugins run under least privilege; secrets protected; runbooks are executable |
| CNF | Sandbox with no network by default; secret scanning in CI; actionable alerts |
| DoR | E1 (plugin permissions) and a base Execution Sandbox available |
| DoD | Sandbox network-denial test; runbooks published; alerts configured |
| Dependencies | E1, E8-S4 |

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
