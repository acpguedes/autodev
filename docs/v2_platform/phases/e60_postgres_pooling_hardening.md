# E60 — Connection Pooling and PostgreSQL Hardening

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/4
**Depends on:** E51-E55 (functional parity first — this epic deliberately
runs last), E57 (a real environment to measure against), E11-S1 / ADR-017
(the observability runtime the new metrics plug into)
**Enables:** running multiple application replicas without exhausting
PostgreSQL connections, leaking tenant context between requests, or leaving
transactions abandoned.
**Canonical source:** this document, from a direct read of the current tree
(`d07b746`): `psycopg_pool`, `ConnectionPool`, and `pool_size` return zero
matches across `backend/`; `backend/requirements.txt:12` pins
`psycopg[binary]`, not `psycopg[pool]`.

## Context and problem

Every PostgreSQL operation opens its own connection.
`backend/persistence/postgres_adapter/_shared.py:10-28` calls
`psycopg.connect(database_url)` per call, and `PostgresStore.connect()`
(`store.py:38-40`) is invoked per method. With one process and light traffic
this is merely wasteful. With several replicas under load it is a connection
exhaustion incident: PostgreSQL's `max_connections` is a hard limit, and
nothing in the application bounds its own demand.

There is also no `statement_timeout`, no `lock_timeout`, and no
`idle_in_transaction_session_timeout`. A single stuck query or an abandoned
transaction can hold locks indefinitely — and the row locks E51-E55 introduce
make that materially more likely than it was before this program.

Pooling introduces a security concern that did not previously exist. Tenant
scoping works by setting `app.tenant_id` inside a transaction via
`set_config(..., true)`. That is transaction-local, which is correct today
because connections are not reused. Once connections return to a pool,
anything that leaves session state behind — a `SET` outside a transaction, a
connection returned mid-transaction — becomes a cross-tenant data leak. This
epic must make that impossible rather than merely unlikely.

Sequencing is deliberate: hardening a store that does not yet work on
PostgreSQL would be premature, so this epic runs after functional parity.

## Evidence in code

- `psycopg_pool`, `ConnectionPool`, `pool_size` — zero occurrences under
  `backend/`.
- `backend/requirements.txt:12` — `psycopg[binary]>=3.2`; the `pool` extra is
  not installed.
- `backend/persistence/postgres_adapter/_shared.py:10-28` — `_connect()`
  calls `psycopg.connect(database_url)`.
- `backend/persistence/postgres_adapter/store.py:38-40` —
  `PostgresStore.connect()` per method call.
- `backend/quotas/migrations.py:137` and `backend/ops/doctor.py:119` — further
  ad-hoc connections.
- Partial precedent for reuse: `backend/auth/store.py:419-429` and
  `backend/artifacts/pointers.py` cache one connection per thread in
  `threading.local()` with `_drop_connection()` on failure — reuse already
  exists in the codebase, without pooling and without RLS-safety handling.
- `backend/persistence/tenancy.py:20-45` — `set_config('app.tenant_id', %s,
  true)`, transaction-local by design.
- No `statement_timeout`, `lock_timeout`, or
  `idle_in_transaction_session_timeout` anywhere in the repository.
- `docs/ops/observability.md` — the metric-label cardinality policy any new
  metric must follow.

## Objective

Introduce bounded, observable connection pooling with safe session-state
handling and explicit timeouts, so the platform runs on multiple replicas
predictably, and so failures are visible before they become outages.

## Key result

Multiple replicas operate without connection-count explosion, without tenant
context surviving a connection's return to the pool, and without abandoned
transactions holding locks — with pool, lock, deadlock, and slow-query
signals visible in the existing observability stack.

## Scope

- A connection pool, preferably `psycopg_pool`.
- Minimum and maximum pool size, and behavior under exhaustion.
- Graceful shutdown.
- Session-state and RLS safety on connection return.
- `statement_timeout`, `lock_timeout`,
  `idle_in_transaction_session_timeout`.
- Retry limited to transient, safe errors.
- Deadlock detection.
- Metrics for connections, pool wait, locks, deadlocks, slow queries, table
  sizes, and the HNSW index.
- Readiness and liveness.
- Index analysis with `EXPLAIN ANALYZE`.
- A minimum load test.
- Explicit limits and SLOs.

## Out of scope

- Functional parity work (E51-E55) — a prerequisite, not part of this epic.
- An external connection pooler such as PgBouncer; if measurement later
  justifies one, that is a deployment decision with its own ADR.
- Read replicas and horizontal read scaling.
- Retrieval quality tuning; index analysis here is about query plans and
  cost, not recall.

## Stories

### E60-S1 — Connection pool

Subtasks:
- `E60-S1-T1`: introduce `psycopg_pool` behind the E49 contract so callers
  acquire connections through the same interface and no call site changes,
  and add the `pool` extra to requirements.
- `E60-S1-T2`: configure minimum and maximum size, and define behavior under
  exhaustion — bounded wait then a typed error, never an unbounded queue that
  converts saturation into a hang.
- `E60-S1-T3`: graceful shutdown that drains in-flight work and closes
  connections; reconcile or remove the `threading.local()` caching in
  `auth/store.py` and `artifacts/pointers.py` so there is one reuse
  mechanism, not two.

| Criterion | Detail |
| --- | --- |
| Functional | All PostgreSQL access goes through the pool; behavior unchanged under normal load |
| Non-functional | Connection count is bounded and configurable; exhaustion yields a typed error within a bounded wait; shutdown leaks no connections |
| DoR (specific) | E51-E55 merged |
| DoD (specific) | Test asserting the connection cap holds under concurrent load, and a clean-shutdown test |
| Dependencies | E49, E51-E55 |

### E60-S2 — Session-state and RLS safety

Subtasks:
- `E60-S2-T1`: guarantee that a connection returned to the pool carries no
  residual session state — no lingering `app.tenant_id`, no open transaction,
  no `SET` outside a transaction.
- `E60-S2-T2`: a cross-tenant leak test that is a genuine negative control:
  tenant A's request, then tenant B's request served by the same pooled
  connection, asserting B cannot observe A's rows and that an unset tenant
  yields no rows rather than all rows.
- `E60-S2-T3`: ensure a connection returned mid-transaction is rolled back
  and reset before reuse, never handed to the next caller in an unknown
  state.

| Criterion | Detail |
| --- | --- |
| Functional | Tenant context never survives a connection's return; reused connections are always in a clean state |
| Non-functional | The guarantee is structural — enforced on return, not by caller discipline |
| DoR (specific) | E60-S1 merged |
| DoD (specific) | Cross-tenant leak test green, including the unset-tenant case |
| Dependencies | E60-S1, E50-S4 |

### E60-S3 — Timeouts, retry and deadlocks

Subtasks:
- `E60-S3-T1`: set `statement_timeout`, `lock_timeout`, and
  `idle_in_transaction_session_timeout` with documented defaults, chosen so
  the row-lock critical sections from E51-E55 fit comfortably within them.
- `E60-S3-T2`: retry only transient, safe errors — serialization failures and
  deadlock victims — with bounded attempts and backoff, and never retry a
  non-idempotent operation whose outcome is unknown.
- `E60-S3-T3`: detect and surface deadlocks distinctly from generic failures,
  so lock-ordering defects are diagnosable rather than appearing as random
  errors.

| Criterion | Detail |
| --- | --- |
| Functional | A stuck query, a stuck lock wait, and an abandoned transaction each terminate within their configured bound |
| Non-functional | Retry is restricted to safe classes; deadlocks are distinguishable in logs and metrics |
| DoR (specific) | E60-S2 merged |
| DoD (specific) | Tests for each timeout firing, and a deadlock produced and correctly classified |
| Dependencies | E60-S2, E51-E55 |

### E60-S4 — Metrics, index analysis and SLOs

Subtasks:
- `E60-S4-T1`: metrics for connections in use, pool wait time, lock waits,
  deadlocks, slow queries, table sizes, and HNSW index health, following the
  cardinality policy in `docs/ops/observability.md`.
- `E60-S4-T2`: extend readiness and liveness to reflect pool and database
  health, so a saturated pool is visible to an orchestrator rather than
  presenting as latency.
- `E60-S4-T3`: `EXPLAIN ANALYZE` review of the hot query paths — including
  the tenant-first indexes from E50 and the pending-decision and expiry
  queries from E53 — plus a minimum load test establishing explicit limits
  and SLOs.

| Criterion | Detail |
| --- | --- |
| Functional | Pool and database health are observable and reflected in readiness |
| Non-functional | Hot paths use their intended indexes, verified by query plans; limits and SLOs are stated numbers from measurement |
| DoR (specific) | E60-S3 merged; E57 available for measurement |
| DoD (specific) | Dashboard/alert coverage, query-plan evidence, and a load-test report with stated SLOs |
| Dependencies | E60-S3, E11-S1, E57 |

## Contracts and decisions

### Architectural decisions required

- No new ADR is required for pooling itself — it is an implementation of
  ADR-001's production posture, and ADR-017 already defines the observability
  runtime the metrics use.
- Two situations would require one, decided at the time rather than assumed:
  adopting an external pooler such as PgBouncer, whose transaction-pooling
  mode interacts directly with the session-state assumptions in E60-S2; or
  changing the tenant-scoping mechanism away from a transaction-local GUC.

### Security and multitenancy

- E60-S2 is the security core of this epic. Pooling is the first change in
  the program that could reintroduce cross-tenant data access *after* RLS is
  correctly in place, because RLS enforcement depends on session state that
  pooling makes shareable.
- The unset-tenant case must yield no rows rather than all rows — a policy
  reading `current_setting('app.tenant_id', true)` returns NULL when unset,
  and the resulting comparison must not be permissive.
- Timeouts are also a denial-of-service control: an unbounded query holding
  locks is a cross-tenant availability failure.
- Metrics must not encode tenant identifiers as labels; per-tenant volumes
  belong in aggregates.

### Migration strategy

- No schema change.
- Timeout defaults are configuration, introduced with documented values and
  overridable per deployment.

### Compatibility and rollback

- SQLite is unaffected; pooling applies to PostgreSQL only.
- Rollback is disabling the pool and returning to per-operation connections,
  which must remain viable throughout — the contract, not the pool, is the
  interface.
- Timeout defaults must not break the row-lock sections from E51-E55; they
  are chosen against measured durations, not guessed.

## Testing and observability

Tests required:
- Connection cap held under concurrent load.
- Bounded wait and typed error on exhaustion.
- Clean shutdown with no leaked connections.
- Cross-tenant leak negative control, including the unset-tenant case.
- Mid-transaction return rolled back and reset.
- Each timeout firing.
- Deadlock produced and classified distinctly.
- Query plans for hot paths.
- Load test establishing SLOs.

Observability:
- New metrics land in the existing OpenTelemetry meter (E11-S1) and follow
  the documented cardinality policy.
- Readiness reflects pool saturation.
- Alerts for pool exhaustion and rising deadlock rates, alongside the
  existing backup alerts.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Tenant context survives connection reuse | Cross-tenant data exposure — the most severe risk in the program | Structural reset on return (E60-S2-T1) plus a negative-control leak test (E60-S2-T2) |
| Unset tenant treated permissively | Every tenant's rows returned | Explicitly asserted: unset yields no rows (E60-S2-T2) |
| Timeouts set below real critical-section durations | Legitimate quota and secret operations fail under load | Defaults chosen from measured durations (E60-S3-T1), validated by the load test |
| Retry applied to non-idempotent operations | Duplicated side effects | Retry restricted to serialization failures and deadlock victims (E60-S3-T2) |
| Pool exhaustion presents as latency, not saturation | Misdiagnosed incidents | Pool wait metric plus readiness reflecting saturation (E60-S4-T1, T2) |
| Metrics carry tenant labels | Cardinality explosion and a privacy concern | Follow the existing cardinality policy explicitly |

## DoR / DoD

- **DoR:** E51-E55 merged (functional parity exists); E57 available for
  measurement; timeout candidate values derived from measured critical
  sections rather than chosen arbitrarily.
- **DoD:** all four story DoDs met; multiple replicas operate within a bounded
  connection count; the cross-tenant leak test passes as a genuine negative
  control; timeouts and deadlock handling proven; metrics, readiness, query
  plans, and SLOs published; `docs/v2_platform/progress.md` updated; no push
  or PR without explicit authorization.

## Exit evidence

1. Load-test output showing a bounded connection count across replicas, with
   stated SLOs.
2. Cross-tenant leak test output, including the unset-tenant case.
3. Timeout tests showing each of the three firing.
4. A deadlock produced and classified distinctly in logs and metrics.
5. `EXPLAIN ANALYZE` output for the hot query paths.

## Affected documents and code

Documents: `docs/config.md` (pool size and timeout variables),
`docs/ops/observability.md` (new metrics and alerts),
`docs/v2_platform/progress.md`, `docs/feature_matrix.md`,
`docs/v2_platform/runbooks/e11_incident_response.md` (pool exhaustion and
deadlock response).

Code: `backend/persistence/` (pool behind the contract),
`backend/persistence/postgres_adapter/_shared.py`,
`backend/auth/store.py` and `backend/artifacts/pointers.py`
(`threading.local()` reconciliation), `backend/requirements.txt`,
`backend/ops/doctor.py`, `backend/quotas/migrations.py`,
`infrastructure/observability/prometheus-rules.yml`.
