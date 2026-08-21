# E54 — EnvironmentStore on PostgreSQL

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/3
**Depends on:** E49 (persistence contract), E50-S2 (environment migrations),
E32 / ADR-013 (isolated execution environments and the isolation backend)
**Enables:** isolated execution environments to be tracked durably in the
`prod` profile, with per-tenant concurrency limits that hold across replicas
and orphaned environments that are recoverable after a process crash.
**Canonical source:** this document, from a direct read of the current tree
(`d07b746`): `EnvironmentStore` raises `ValueError` on the `postgresql://`
URL the `prod` profile mandates, so the record of which sandboxes exist
cannot be kept in production.

## Context and problem

`EnvironmentStore` is the durable ledger for isolated execution environments:
which exist, what state each is in, and which decisions were taken about
them. It is SQLite-only and refuses a PostgreSQL URL
(`backend/environments/store.py:38`).

Two consequences matter beyond reachability. First, a per-tenant limit on
concurrent environments enforced against a process-local SQLite file is not a
limit at all once more than one replica runs — each replica would enforce its
own count. Second, environments are external resources: a container that
outlives the process that created it becomes an orphan consuming CPU, memory,
and disk, with no durable record to reap it from. Both properties depend on
the ledger being shared and transactional, which is exactly what the
PostgreSQL port provides.

## Evidence in code

- `backend/environments/store.py:30-39` — private `_resolve_db_path`; `:38`
  raises `ValueError("EnvironmentStore requires a sqlite:// DATABASE_URL")`.
- `backend/environments/store.py:118` — `sqlite3.connect(...)`.
- `backend/environments/store.py:126, 143` — `execution_environments` and
  `execution_environment_decisions` created by `CREATE TABLE IF NOT EXISTS`,
  outside `MigrationRunner`.
- `backend/environments/store.py:163-257` — `?` placeholders and
  `sqlite3.Row` throughout; **no `BEGIN IMMEDIATE`**, so the concurrent-limit
  check has no explicit serialization even on SQLite.
- `backend/environments/manager.py:100` — `self._store = store or
  EnvironmentStore()`, no injection point in production.
- `backend/persistence/migrations/postgres_versions.py` — neither table
  present.
- `docs/v2_platform/runbooks/e35_isolation_violation_incident.md` — documents
  `AUTODEV_EXECUTION_ENVIRONMENT_BACKEND=unavailable` as a config-level kill
  switch, which the port must keep working.

## Objective

Port `EnvironmentStore` to both backends through the E49 contract, so the
environment lifecycle is durable and transactional, the per-tenant
concurrency limit is enforced by the database across replicas, and orphaned
environments are detectable and reapable after a crash.

## Key result

The concurrent-environment limit holds when several application instances
request environments simultaneously, and an environment orphaned by a process
crash is found and reclaimed by another replica.

## Scope

- The environment lifecycle: creation, provisioning, execution, collection,
  teardown.
- Environment decision records.
- Expiry and reaping of orphaned environments.
- Per-tenant concurrent-environment limits enforced across replicas.
- Recovery after process failure.
- Idempotent operations.
- Multitenant isolation.

## Out of scope

- Changing the isolation backend or sandbox mechanics — ADR-013 stands; this
  epic is about the durable ledger, not the container runtime.
- The two migrations themselves (E50-S2-T2).
- Execution *policy* decisions, which live in `PolicyStore` and E53.
- Pooling and timeouts (E60).

## Stories

### E54-S1 — Environment lifecycle on both backends

Subtasks:
- `E54-S1-T1`: move `EnvironmentStore` onto the E49 contract — remove
  `sqlite3.connect`, the private `_resolve_db_path`, the PostgreSQL rejection
  guard, and `_create_schema`.
- `E54-S1-T2`: port the lifecycle transitions (create → provision → execute →
  collect → teardown), keeping the observable state machine unchanged.
- `E54-S1-T3`: make each transition idempotent, so a retried teardown or
  collection does not corrupt state or double-record.

| Criterion | Detail |
| --- | --- |
| Functional | Lifecycle transitions behave identically on both backends; `prod` can construct `EnvironmentStore` |
| Non-functional | No `sqlite3` import remains in `backend/environments/store.py`; the kill switch still works |
| DoR (specific) | E49-S2 and E50-S2 merged |
| DoD (specific) | Existing environment tests green on both backends; retried transitions proven idempotent |
| Dependencies | E49, E50-S2, E32 |

### E54-S2 — Decisions and cross-replica concurrency limit

Subtasks:
- `E54-S2-T1`: port `execution_environment_decisions` as a durable audit of
  environment decisions.
- `E54-S2-T2`: enforce the per-tenant concurrent-environment limit inside a
  transaction with row-level locking, so the count-then-create sequence
  cannot interleave across replicas.
- `E54-S2-T3`: prove the limit with concurrent requests from multiple
  connections — the invariant is that the limit is never exceeded, not that
  requests are fast.

| Criterion | Detail |
| --- | --- |
| Functional | Concurrent creation requests never exceed the tenant's configured limit |
| Non-functional | The limit is enforced by the database, not by in-process counters; decisions are durably recorded |
| DoR (specific) | E54-S1 merged |
| DoD (specific) | Concurrency test with N simultaneous creations against a limit of M, asserting the invariant |
| Dependencies | E54-S1 |

### E54-S3 — Expiry, reaping and crash recovery

Subtasks:
- `E54-S3-T1`: expire environments past their lifetime and mark them for
  teardown, with expiry claimed exactly once under concurrency.
- `E54-S3-T2`: reap orphans — environments whose owning process died leaving
  the record in a non-terminal state — so another replica can reclaim them
  and free the underlying resources.
- `E54-S3-T3`: crash-recovery test: kill the owner mid-lifecycle and assert a
  second instance reclaims the environment and that the tenant's concurrency
  count returns to a correct value.

| Criterion | Detail |
| --- | --- |
| Functional | Expired and orphaned environments are reclaimed exactly once; the concurrency count recovers |
| Non-functional | Reaping is safe to run on every replica simultaneously |
| DoR (specific) | E54-S2 merged; E50-S4 RLS applied to both tables |
| DoD (specific) | Crash-recovery test green; concurrent reaping produces no double-teardown |
| Dependencies | E54-S2, E50-S4 |

## Contracts and decisions

### Architectural decisions required

- No new ADR. ADR-013 fixes the isolation backend; this epic changes where
  the ledger lives, not how isolation works. A change to environment
  lifecycle semantics would need an amendment referencing ADR-013 and is not
  expected.

### Security and multitenancy

- The concurrency limit is a resource-exhaustion control: a limit that does
  not hold across replicas lets one tenant starve the host. This is the
  security-relevant part of the epic.
- Both tables are RLS-protected by E50-S4; one tenant must not observe or
  reap another tenant's environments.
- Reaping must not tear down an environment that another replica legitimately
  owns — the claim must be transactional.
- The `AUTODEV_EXECUTION_ENVIRONMENT_BACKEND=unavailable` kill switch from
  the E35 isolation-violation runbook must keep working after the port.

### Migration strategy

- No schema work here (E50-S2-T2).
- `_create_schema` is removed; both tables come under `schema_version` for
  the first time.

### Compatibility and rollback

- SQLite local-first behavior preserved; a single-process local install
  behaves as before.
- Existing SQLite environment records are untouched; moving them is E58 —
  though environment records are short-lived by nature, so E58 should treat
  non-terminal environments explicitly rather than copying them blindly.
- Rollback is reverting the port; E50's tables remain present and unused.

## Testing and observability

Tests required:
- Existing environment suites, green on both backends.
- Idempotent retried transitions.
- Concurrent creation against a tenant limit.
- Expiry claimed exactly once.
- Crash recovery: owner dies, another replica reclaims.
- Concurrent reaping producing no double-teardown.
- Tenant isolation on both tables.

Observability:
- Environment lifecycle events must keep flowing to the existing event
  catalog so the E43 execution-transparency surfaces stay accurate.
- Orphan count is a genuinely useful operational signal; if added, it follows
  the cardinality policy in `docs/ops/observability.md` and is not labelled
  per environment id.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Limit checked outside a transaction | Tenant exceeds its environment quota; host resource exhaustion | E54-S2-T2 performs check and create in one locked transaction; concurrency test is a DoD gate |
| Reaping tears down a live environment | Running work destroyed | Transactional claim before teardown (E54-S3-T2); concurrent-reaping test |
| Orphans never reclaimed | Slow resource leak until host exhaustion | E54-S3-T2 plus the crash-recovery test in E54-S3-T3 |
| Kill switch broken by the port | Isolation incident cannot be contained | Explicit check in E54-S1 DoD, referencing the E35 runbook |
| E58 copies non-terminal environments to PostgreSQL | Phantom environments referencing containers that no longer exist | Flagged here as an input to E58's ordering rules |

## DoR / DoD

- **DoR:** E49-S2 and E50-S2 merged; a real PostgreSQL available to the test
  suite; the E35 isolation runbook re-read so the kill switch is preserved.
- **DoD:** all three story DoDs met; `prod` constructs and uses
  `EnvironmentStore` on PostgreSQL; the concurrency limit proven across
  connections; crash recovery proven; `docs/v2_platform/progress.md` updated;
  no push or PR without explicit authorization.

## Exit evidence

1. Concurrency test output: N simultaneous creation requests against a limit
   of M, never exceeding M.
2. Crash-recovery output showing a second instance reclaiming an orphan and
   the concurrency count returning to correct.
3. Concurrent-reaping output showing no double-teardown.
4. Kill-switch behavior unchanged after the port.

## Affected documents and code

Documents: `docs/v2_platform/progress.md`, `docs/feature_matrix.md`
(execution-environment rows),
`docs/v2_platform/runbooks/e35_isolation_violation_incident.md`,
`docs/v2_platform/beta_acceptance_flow.md` (negative path N3, isolation
violation).

Code: `backend/environments/store.py`, `backend/environments/manager.py`.
