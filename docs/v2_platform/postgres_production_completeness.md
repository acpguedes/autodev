# PostgreSQL Production Completeness — Beta Program (E48-E60)

> Program document for the thirteen Beta-hardening epics that make PostgreSQL
> the sole source of truth for relational state in the `prod` profile. Written
> 2026-08-21, planning only — no code, schema, or migration was changed.
> Epic detail lives in `phases/e48_*.md` … `phases/e60_*.md`; status is
> tracked in `progress.md`, which remains the canonical tracker.

## 1. Current problem

`AUTODEV_PROFILE=prod` **requires** a PostgreSQL `DATABASE_URL`
(`backend/config/settings.py:332-336`). Five domain stores bypass the
persistence layer, call `sqlite3.connect()` directly, and **reject** exactly
that URL:

| Store | File:line | Behavior with a `postgresql://` URL |
| --- | --- | --- |
| `QuotaStore` | `backend/quotas/store.py:70` (guard `:49`) | raises `ValueError` |
| `SecretStore` | `backend/secret_store/store.py:83` (guard `:48`) | raises `ValueError` |
| `PolicyStore` | `backend/execution/policy.py:227` (guard `:206`) | raises `ValueError` |
| `EnvironmentStore` | `backend/environments/store.py:118` (guard `:38`) | raises `ValueError` |
| `StepApprovalStore` | `backend/plans/step_state.py:177` (fallback `:132`) | **silently** writes `./autodev_plan_step_state.db` |

Their services construct them with no injection point
(`quotas/service.py:87`, `secret_store/service.py:50`,
`execution/decisions.py:65`, `execution/policy.py:565`,
`environments/manager.py:100`).

The consequence is stronger than degradation. In a valid production
configuration, quotas, secrets, execution policy, and execution environments
**cannot be instantiated at all**, and plan-step approval state is a local
SQLite file that no replica shares and no backup manifest covers.

Four further verified defects:

1. **The shipped `prod` stack cannot run its own migrations.**
   `backend/persistence/migrations/postgres_versions.py:253` executes
   `CREATE EXTENSION IF NOT EXISTS vector` unconditionally;
   `infrastructure/docker-compose.yml:116` ships stock `postgres:16-alpine`,
   which does not bundle it.
2. **Thirteen tables have no PostgreSQL migration.** All are created by
   `CREATE TABLE IF NOT EXISTS` inside `_create_schema`, outside
   `MigrationRunner`, so none is tracked in `schema_version` and none has a
   `down` path or RLS.
3. **No PostgreSQL runs in CI.** No workflow in `.github/workflows/` has a
   `services:` block. Every PostgreSQL path — both adapter packages, all
   seven migrations, RLS, pgvector — is exercised only against a
   monkeypatched `sys.modules["psycopg"]`.
4. **Documentation asserts what the code does not do.**
   `docs/feature_matrix.md:25` lists PostgreSQL persistence as working
   `optional`; ADR-001 declares PostgreSQL the default production state
   store; `beta_gap_analysis.md` records **no** PostgreSQL gap. Beta is being
   assessed against an untrue premise.

Defect 3 is the root cause of the rest: the divergence could exist for as long
as it has precisely because nothing ever asked a store to behave identically
on both backends.

## 2. Desired state

- PostgreSQL is the only source of truth for relational state in `prod`.
- The `prod` profile creates and depends on no SQLite `.db` file.
- SQLite continues to work, first-class, in the `local` profile.
- Redis stays responsible for queues, cache, locks, and streams; anything in
  Redis remains reconstructible from PostgreSQL (reference §13.4).
- MinIO/S3 stays responsible for artifact payloads; databases hold pointers.
- PostgreSQL with `pgvector` works in the local production-like stack and on
  managed providers.
- Every endpoint and store has functional parity across SQLite and
  PostgreSQL.
- Multitenant isolation, migrations, backup, restore, and concurrency are
  proven by tests against a real PostgreSQL.

## 3. Architectural principles

1. **Local-first is not legacy.** SQLite parity is a requirement, not a
   courtesy; the contract suite (E56) holds both backends to one contract.
2. **No ORM.** SQL text stays explicit. E49 extracts a minimal dialect
   abstraction covering only operations the codebase already uses — the same
   stance E47-S4 recorded when it rejected a generic adapter.
3. **Isolation belongs to the database.** `tenant_id` plus RLS with `FORCE`,
   per ADR-010, not application `WHERE` clauses alone.
4. **Schema comes from migrations.** No store creates its own tables; every
   table is versioned and reversible.
5. **Fail closed.** Missing capability, unreachable store, or unmet
   precondition denies rather than degrades silently. The current
   `StepApprovalStore` fallback is the anti-pattern this program removes.
6. **Mocked connections are not PostgreSQL evidence.** Fakes remain fine for
   fast unit tests; no Beta criterion may be marked met on their basis. This
   extends the "fact vs. recommendation" discipline from E35-S1-T3.
7. **Correctness before performance.** Pooling and hardening (E60) run last,
   after functional parity, so they optimize a system that works.

## 4. Child epic inventory

| ID | Epic | Stories | Main criterion |
| --- | --- | ---: | --- |
| [E48](phases/e48_postgres_runtime_pgvector.md) | PostgreSQL Runtime with pgvector | 4 | `prod` starts from zero with PG16 + pgvector and runs a real vector query |
| [E49](phases/e49_shared_sql_infrastructure.md) | Shared SQL Persistence Infrastructure | 4 | Domain stores depend on a persistence contract, not on `sqlite3` or `psycopg` |
| [E50](phases/e50_postgres_schema_migrations_rls.md) | PostgreSQL Schema, Migrations, Tenancy and RLS | 4 | Every relational table `prod` needs is created exclusively by versioned migrations |
| [E51](phases/e51_quotastore_postgres_concurrency.md) | QuotaStore on PostgreSQL and Concurrency | 4 | Under real concurrency, consumption never exceeds quota; no duplicate reservations or leases |
| [E52](phases/e52_secretstore_postgres.md) | SecretStore on PostgreSQL | 3 | Two concurrent rotations create no invalid versions and no inconsistent active version |
| [E53](phases/e53_policystore_postgres.md) | PolicyStore on PostgreSQL | 3 | A pending decision reaches a terminal state exactly once, even under concurrent requests |
| [E54](phases/e54_environmentstore_postgres.md) | EnvironmentStore on PostgreSQL | 3 | The concurrent-environment limit holds across instances; orphans are recoverable |
| [E55](phases/e55_plan_step_state_postgres.md) | Plan Step State on PostgreSQL | 3 | Step approval works with multiple replicas and no SQLite file is created in `prod` |
| [E56](phases/e56_sqlite_postgres_contract_tests.md) | SQLite/PostgreSQL Contract Test Suite | 3 | The same functional contract passes in full on SQLite and PostgreSQL |
| [E57](phases/e57_ci_postgres_e2e.md) | CI and Real PostgreSQL E2E | 4 | Every pull request runs at least one real E2E flow in the `prod` profile |
| [E58](phases/e58_sqlite_to_postgres_migration.md) | SQLite to PostgreSQL Data Migration | 4 | An existing SQLite install is promoted without loss, duplication, or semantic change |
| [E59](phases/e59_backup_restore_disaster_recovery.md) | Backup, Restore and Disaster Recovery | 3 | An empty environment is rebuilt entirely from a validated backup |
| [E60](phases/e60_postgres_pooling_hardening.md) | Connection Pooling and PostgreSQL Hardening | 4 | Multiple replicas run without connection explosion, tenant leak, or abandoned transactions |

**Total: 46 stories across 13 epics.**

## 5. Execution order and dependencies

```
E48 Runtime pgvector
        |
E49 Shared SQL infrastructure
        |
E50 Schema, migrations and RLS
        |
        +--> E51 Quota
        +--> E52 Secrets
        +--> E53 Policies      (parallel once E49 + E50 land)
        +--> E54 Environments
        +--> E55 Plan steps
                    |
E56 Contract tests <+
        |
E57 CI and prod E2E
        |
E58 SQLite -> PostgreSQL migration
        |
E59 Backup and disaster recovery
        |
E60 Pooling and hardening
```

E51-E55 are the only epics intended to run in parallel, and only after E49
and E50 are merged. E60 runs last by design.

Two dependency notes worth stating explicitly:

- **E50 creates tables before E51-E55 read them.** That intermediate state is
  intentional: RLS is in force from the first write, and E57 asserts schema
  rather than usage until the ports land.
- **E51-S4 and E56 need a real PostgreSQL**, which E57-S1 provides in CI.
  Until E57 lands, those tests run against the local Compose `postgres`
  profile.

## 6. Requirement traceability matrix

Every requirement of the program brief, mapped to where it is satisfied.

| Requirement | Epic | Story | Completion evidence |
| --- | --- | --- | --- |
| Replace `postgres:16-alpine` with a pgvector-capable image | E48 | E48-S1 | From-empty `prod` bring-up applying all 7 migrations |
| PostgreSQL/pgvector version compatibility | E48 | E48-S1-T3 | Documented supported version pairs, pinned in Compose and CI |
| Execute or provision `CREATE EXTENSION vector` | E48 | E48-S2-T1 | Migration succeeds with extension pre-installed and no create privilege |
| Support managed providers without extension privileges | E48 | E48-S2-T2 | Three-case provisioning test matrix |
| Preflight: connection, version, extension, permission, HNSW index | E48 | E48-S3-T1 | One distinguishable failure per condition |
| Fail before starting the API when requirements are unmet | E48 | E48-S3-T2 | Fail-closed boot test |
| Document extension install, upgrade, rollback | E48 | E48-S4 | Updated `docs/config.md` and ops docs |
| Common connection from the configured State Store | E49 | E49-S1-T1 | Five private `_resolve_db_path` copies removed |
| Placeholders `?` and `%s` | E49 | E49-S1-T2 | Dialect tests on both backends |
| Transaction begin/end | E49 | E49-S2-T1 | Mutual-exclusion test on both backends |
| Upserts, `RETURNING`, timestamps, row decoding | E49 | E49-S1-T2, E49-S2-T3 | Dialect and codec tests |
| Integrity errors mapped to one type | E49 | E49-S1-T2 | Uniqueness violation raises the shared type on both backends |
| Tenant application in the contract | E49 | E49-S1-T3 | Isolation tests via a single call site |
| Preserve explicit SQL; no ORM without ADR | E49 | E49-S1, ADR-025 | ADR-025 `Accepted` recording the no-ORM stance |
| Reduce duplication between stores | E49 | E49-S3 | Eight stores migrated; no `template.format(p=` left in domain code |
| Avoid `if postgres` spread across methods | E49 | E49-S3 | No dialect conditionals in migrated method bodies |
| Encapsulate backend-specific operations | E49 | E49-S1-T2, E49-S2-T2 | Named operations, not inline conditionals |
| Keep SQLite local-first | E49, E56 | E49-S1, E56-S2 | Contract suite green on SQLite |
| Rule: no `sqlite3.connect()` outside persistence | E49 | E49-S4 | Guard test with a shrinking documented allowlist |
| Versioned migrations for the 13 tables | E50 | E50-S1, E50-S2, E50-S3 | `schema_version` after a from-empty migration |
| `up` and `down` migrations | E50 | E50-S4-T3 | Up → down → up round-trip test |
| Constraints, foreign keys, indexes | E50 | E50-S1-T3, E50-S2-T3 | Index and constraint assertions |
| PostgreSQL types, `JSONB`, `TIMESTAMPTZ` | E50 | E50-S1, E50-S2 | Type assertions; cross-backend shape tests in E56 |
| Idempotency and version compatibility | E50 | E50-S4-T3 | Idempotent re-run; `SchemaVersionMismatchError` preserved |
| `tenant_id NOT NULL` | E50 | E50-S1-T3, E50-S3-T1 | Column assertions on all 13 tables |
| Tenant-first indexes | E50 | E50-S1-T3 | Index definition review |
| `ENABLE` and `FORCE ROW LEVEL SECURITY` | E50 | E50-S4-T1 | `pg_class` showing both true for all 13 |
| Policies on `current_setting('app.tenant_id', true)` | E50 | E50-S4-T1 | Policy definitions; isolation tests |
| Tenant isolation tests | E50, E56 | E50-S4-T3, E56-S3-T2 | Two-tenant tests, both directions, per table |
| Review `plan_step_state`, which lacks `tenant_id` | E50 | E50-S3-T1 | `tenant_id NOT NULL` added on both backends |
| Foreign key from `plan_step_state` to session or plan | E50 | E50-S3-T2 | FK constraint present; backfill test |
| Old → updated → reverted migration consistency | E50 | E50-S4-T3 | Round-trip test output |
| Quota policies, usage windows | E51 | E51-S1 | Quota tests green on both backends |
| Execution leases | E51 | E51-S2 | Concurrent acquire yields one holder |
| Storage reservations | E51 | E51-S3-T1 | Double-commit rejected |
| Rate limiting | E51 | E51-S3-T2 | Rate bucket tests on both backends |
| Replace `BEGIN IMMEDIATE` | E49, E51 | E49-S2-T1, E51-S1 | No `BEGIN IMMEDIATE` in quota code |
| `SELECT ... FOR UPDATE`, conditional updates, `ON CONFLICT`, `RETURNING` | E51 | E51-S1-T3, E51-S2-T1 | Concurrency suite; the false docstring corrected |
| Prevent oversubscription and double commit | E51 | E51-S4-T1 | Consumption never exceeds quota under concurrency |
| Expired leases, idempotency | E51 | E51-S2-T2, E51-S2-T3 | Expiry reclaimed exactly once |
| Concurrency across processes and replicas | E51 | E51-S4-T2 | Cross-process test |
| Tests with multiple real PostgreSQL connections | E51 | E51-S4-T1 | Multi-connection suite output |
| Secret creation, rotation, revocation | E52 | E52-S1-T2 | Secret tests green on both backends |
| Latest active version resolution | E52 | E52-S2-T2 | Exactly-one-active-version constraint |
| Ciphertext-only storage | E52 | E52-S1-T3 | No-plaintext assertions |
| Concurrency between rotations | E52 | E52-S2-T1 | Concurrent rotation leaves a coherent chain |
| Version constraints | E52 | E52-S2-T2 | Database constraint, not application-only |
| Isolation by tenant, project, name | E52 | E52-S3-T1 | Same-name-different-tenant test |
| Audit; no plaintext in DB, logs, events | E52 | E52-S3-T2 | Audit and no-plaintext assertions |
| Fail-closed | E52 | E52-S3-T3 | Unavailability denies rather than resolving empty |
| Compatibility with the existing encryption key | E52 | E52-S1-T3 | Pre-port ciphertext decrypts after the port |
| Execution rules, dynamic permissions | E53 | E53-S1 | Policy tests green on both backends |
| Decision audit; pending human decisions | E53 | E53-S2-T1, E53-S2-T2 | Append-only audit; exactly-once terminal state |
| Atomic transitions; no double approval or rejection | E53 | E53-S2-T2 | Concurrent approve/reject yields one outcome |
| Expiration; idempotent resolution | E53 | E53-S3-T1, E53-S2-T3 | Expiry and replay tests |
| Multitenant isolation; fail-closed in production | E53 | E53-S3-T3 | Isolation and denial tests |
| Indexes for pending and expired decisions | E53 | E53-S3-T2 | Query plans confirming index use |
| Environment creation, provisioning, execution, collection, teardown | E54 | E54-S1-T2 | Lifecycle tests on both backends |
| Expiry and reaping of orphans | E54 | E54-S3-T1, E54-S3-T2 | Reclaimed exactly once |
| Concurrent limit per tenant | E54 | E54-S2-T2 | N concurrent creations never exceed the limit |
| Recovery after process failure | E54 | E54-S3-T3 | Crash-recovery test |
| Decision auditing; idempotent operations | E54 | E54-S2-T1, E54-S1-T3 | Durable decisions; retried transitions idempotent |
| Concurrency across replicas | E54 | E54-S2-T3 | Multi-connection test |
| Eliminate `./autodev_plan_step_state.db` | E55 | E55-S3-T2 | No `.db` file created under `prod` |
| Move `plan_step_state` to the State Store | E55 | E55-S1-T1 | Reads and writes go to the configured store |
| Add `tenant_id` and a plan/session relationship | E50, E55 | E50-S3, E55-S1-T2 | Schema plus tenant-scoped operations |
| Preserve the six-state machine | E55 | E55-S2-T2 | State machine tests unchanged from E16-S2 |
| Atomic transitions; reject illegal edit/delete | E55 | E55-S2-T2, E55-S2-T3 | Negative tests per illegal transition |
| Replace the local lock with transactional control | E55 | E55-S2-T1 | Two-connection concurrency test |
| SQLite compatibility; migrate existing data | E55 | E55-S1-T3, E55-S3-T1 | Migration report from a populated legacy file |
| Reusable contract suite across both backends | E56 | E56-S1 | One case executing on both via fixture |
| CRUD, upsert, pagination | E56 | E56-S2-T1, E56-S2-T2 | Contract green on both backends |
| Transactions, rollback, uniqueness, equivalent errors | E56 | E56-S2-T3 | Shared exception type asserted |
| Concurrency; tenant isolation | E56 | E56-S3-T1, E56-S3-T2 | Invariants and isolation on both backends |
| Migrations; timestamps and JSON; behavior after restart | E56 | E56-S3-T3, E56-S2-T1 | Round-trip, shape, and durability cases |
| Cases shared, only the backend fixture varies | E56 | E56-S1-T1 | No backend conditionals inside cases |
| Real PostgreSQL 16 + pgvector in CI | E57 | E57-S1-T1 | CI run with a live service |
| Migrations on an empty database; upgrade; rollback | E57 | E57-S1-T2, E57-S1-T3 | CI steps for each |
| Redis and MinIO when the flow needs them | E57 | E57-S2-T3 | `prod` leg services |
| Real `prod` profile initialization | E57 | E57-S3-T1 | Boot through real `validate_profile` |
| API E2E; vector search; two-tenant RLS | E57 | E57-S3-T2 | E2E output with vector result and isolation |
| Concurrency tests in CI | E57 | E57-S3-T3 | Invariants against real connections |
| Backup and restore in CI | E57 | E57-S4-T1, E57-S4-T2 | Round trip plus post-restore smoke test |
| Useful diagnostics on service failure | E57 | E57-S4-T3 | Logs and migration state on failure |
| Matrix: local/SQLite and prod/PG+pgvector+Redis+MinIO | E57 | E57-S2-T1 | Both legs green on a pull request |
| Mocks do not count as PostgreSQL evidence | E57 | §3 principle 6, E57-S2-T2 | PostgreSQL leg fails rather than skips |
| `autodev database migrate --from ... --to ...` | E58 | E58-S1-T1 | Command registered and discoverable |
| Dry run; preflight | E58 | E58-S1-T3, E58-S1-T2 | Dry-run plan; version-mismatch refusal |
| Apply destination schema; consistent source read | E58 | E58-S1-T2, E58-S2-T1 | Preflight and snapshot read |
| Dependency order; ID preservation; sequence adjustment | E58 | E58-S2-T1, E58-S2-T2 | Post-migration insert without collision |
| Timestamps; JSON documents; encrypted secrets | E58 | E58-S2-T3 | Secrets decrypt after migration |
| `autodev_plan_step_state.db` | E58, E55 | E58-S3-T1, E55-S3-T1 | Legacy file migrated with a report |
| Artifacts and pointers | E58 | E58-S3-T2 | Dangling pointers reported |
| Count and hash validation; reconciliation report | E58 | E58-S3-T3 | Per-table reconciliation output |
| Safe resumption; idempotency | E58 | E58-S4-T1 | Interrupt-and-resume without duplication |
| Cutover policy; rollback; no permanent dual-write | E58 | E58-S4-T2, E58-S4-T3 | ADR-026 `Accepted`; cutover runbook |
| PostgreSQL as the complete relational source in backup | E59 | E59-S1-T1 | Enumeration-based coverage assertion |
| `pg_dump` / `pg_restore`; MinIO artifacts | E59 | E59-S1-T1 | Manifest covering all components |
| Manifest, hashes, schema versions | E59 | E59-S1-T1, E59-S1-T3 | Manifest contents |
| Secrets; pgvector extension; vector indexes | E59 | E59-S1-T3 | Extension and index state recorded |
| Restore in a clean environment | E59 | E59-S2-T1 | Clean-environment drill |
| Point-in-time restore where supported | E59 | E59-S3-T1 | PITR implemented or the deviation recorded with an ADR |
| Automated periodic testing | E59 | E59-S2-T3 | Scheduled drill |
| Documented RTO and RPO | E59 | E59-S2-T3, E59-S3-T2 | Measured numbers with a stated method |
| Disaster runbook | E59 | E59-S3-T3 | Updated runbooks |
| No parallel SQLite database outside the backup | E59, E55 | E59-S1-T2, E55-S3-T3 | No stray `.db` in either profile |
| Connection pool, preferably `psycopg_pool` | E60 | E60-S1-T1 | All access through the pool |
| Minimum and maximum size; exhaustion behavior | E60 | E60-S1-T2 | Bounded wait, typed error |
| Graceful shutdown | E60 | E60-S1-T3 | Clean-shutdown test |
| Session state and RLS safety on connection return | E60 | E60-S2 | Cross-tenant leak negative control |
| `statement_timeout`, `lock_timeout`, `idle_in_transaction_session_timeout` | E60 | E60-S3-T1 | Each timeout firing |
| Retry only for safe transient errors | E60 | E60-S3-T2 | Retry restricted to serialization/deadlock classes |
| Deadlock detection | E60 | E60-S3-T3 | Deadlock produced and classified |
| Metrics: connections, pool wait, locks, deadlocks, slow queries, table sizes, HNSW | E60 | E60-S4-T1 | Dashboard and alert coverage |
| Readiness and liveness | E60 | E60-S4-T2 | Readiness reflects pool saturation |
| Index analysis with `EXPLAIN ANALYZE` | E60 | E60-S4-T3 | Query plans for hot paths |
| Minimum load test; explicit limits and SLOs | E60 | E60-S4-T3 | Load-test report with stated SLOs |

## 7. Table matrix

Current PostgreSQL support for the thirteen tables. "PostgreSQL now" was
verified by searching each table name in
`backend/persistence/migrations/postgres_versions.py`: **zero matches for all
thirteen**.

| Table | Store | SQLite | PostgreSQL now | Migration needed | RLS | Contract test |
| --- | --- | --- | --- | --- | --- | --- |
| `tenant_quota_policies` | `QuotaStore` | `quotas/store.py:78` | none | E50-S1 | E50-S4 | E51, E56 |
| `tenant_usage_windows` | `QuotaStore` | `quotas/store.py:84` | none | E50-S1 | E50-S4 | E51, E56 |
| `run_leases` | `QuotaStore` | `quotas/store.py:92` | none | E50-S1 | E50-S4 | E51, E56 |
| `storage_reservations` | `QuotaStore` | `quotas/store.py:101` | none | E50-S1 | E50-S4 | E51, E56 |
| `request_rate_buckets` | `QuotaStore` | `quotas/store.py:110` | none | E50-S1 | E50-S4 | E51, E56 |
| `secrets` | `SecretStore` | `secret_store/store.py:91` | none | E50-S1 | E50-S4 | E52, E56 |
| `execution_policy_rules` | `PolicyStore` | `execution/policy.py:235` | none | E50-S2 | E50-S4 | E53, E56 |
| `execution_dynamic_permissions` | `PolicyStore` | `execution/policy.py:247` | none | E50-S2 | E50-S4 | E53, E56 |
| `execution_policy_decisions` | `PolicyStore` | `execution/policy.py:259` | none | E50-S2 | E50-S4 | E53, E56 |
| `pending_action_decisions` | `PolicyStore` | `execution/policy.py:272` | none | E50-S2 | E50-S4 | E53, E56 |
| `execution_environments` | `EnvironmentStore` | `environments/store.py:126` | none | E50-S2 | E50-S4 | E54, E56 |
| `execution_environment_decisions` | `EnvironmentStore` | `environments/store.py:143` | none | E50-S2 | E50-S4 | E54, E56 |
| `plan_step_state` | `StepApprovalStore` | `plans/step_state.py:159` — **no `tenant_id`** | none | E50-S3 | E50-S4 | E55, E56 |

## 8. Architectural decisions

Three new ADRs, `Proposed`, each decided inside its owning epic — the
ADR-013/014/015 precedent:

| ADR | Title | Epic | Decides |
| --- | --- | --- | --- |
| [ADR-024](decisions/ADR-024-pgvector-runtime-image.md) | pgvector Runtime Image and Extension Provisioning | E48 | Which runtime ships; how the extension is provisioned; managed-provider posture |
| [ADR-025](decisions/ADR-025-sql-persistence-boundary.md) | SQL Persistence Boundary and Dialect Abstraction Scope | E49 | The boundary rule; the dialect surface; the no-ORM stance |
| [ADR-026](decisions/ADR-026-sqlite-to-postgres-migration.md) | SQLite to PostgreSQL Migration and Cutover | E58 | One-way migration; cutover policy; no permanent dual-write |

Existing decisions this program implements rather than revisits: **ADR-001**
(PostgreSQL as default production state store), **ADR-010** (`tenant_id` +
RLS), **ADR-011** (pgvector HNSW), **ADR-014** (secret store format),
**ADR-019** (quotas and run budgets), **ADR-022** (execution policy engine),
**ADR-013** (isolation backend).

One decision is deferred by design: if E59-S3-T1 chooses to meet RPO with
frequent base backups rather than the continuous WAL archiving reference
§13.9 specifies, that deviation needs its own ADR at that time.

## 9. General risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Pooling reintroduces cross-tenant access after RLS is correct | Data exposure — the most severe risk in the program | E60-S2 resets session state structurally on return, with a negative-control leak test; E60 sequenced last so it lands against a proven-correct base |
| Concurrency semantics silently lost translating `BEGIN IMMEDIATE` | Quota oversubscription, double approval, duplicate leases | E49-S2 provides an explicit lock primitive; every port epic proves its invariant with real concurrent connections |
| The abstraction grows into a de-facto ORM | The over-abstraction E47 warned against | ADR-025 fixes the scope to operations already in use; SQL stays explicit |
| Program scope delays Beta sign-off | Beta held open for ~46 stories | Accepted deliberately: Beta cannot be signed off while four subsystems cannot start in `prod`. Recorded as new gate criteria rather than hidden |
| CI runtime grows enough to be bypassed | The blind spot returns by another route | Parallel jobs; the SQLite leg stays fast |
| Data loss during promotion to PostgreSQL | Irrecoverable customer data loss | E58 never mutates the source; reconciliation is a hard gate; rollback is pointing back at the untouched source |
| Secrets rendered undecryptable | Every credential unusable | The migrator never decrypts; ciphertext carried byte-for-byte; compatibility is a DoD gate on E52's first story |
| Tables exist unused between E50 and E51-E55 | Confusing intermediate state | Stated as intended; RLS in force from the first write |

## 10. Global Definition of Done

The program is complete when all of the following hold, each with named
evidence:

1. `AUTODEV_PROFILE=prod` uses PostgreSQL for all relational state.
2. No production endpoint instantiates `sqlite3` directly (E49-S4 guard).
3. No `.db` file is created in the `prod` profile (E55-S3-T3).
4. All thirteen missing tables exist in PostgreSQL (E50).
5. All tenant-scoped tables have RLS with `FORCE` (E50-S4).
6. `up` and `down` migrations are validated (E50-S4-T3).
7. PostgreSQL + pgvector starts via Compose (E48-S1).
8. A real vector query passes (E48, E57-S3-T2).
9. All contracts pass on SQLite and PostgreSQL (E56).
10. The production E2E passes with PostgreSQL, Redis, and MinIO (E57-S3).
11. Concurrency tests pass (E51-E55, E57-S3-T3).
12. Two tenants cannot access each other's data (E50-S4-T3, E56-S3-T2,
    E60-S2-T2).
13. An existing SQLite base is migrated and reconciled (E58).
14. Backup and restore are proven in a clean environment (E59-S2).
15. The local SQLite profile still works (E56, E57-S2).
16. Documentation and runbooks are updated (each epic's affected-documents
    section).

Three of these become new criteria on the v2.0-beta gate in `progress.md`
§18.9: `prod` boots on PG16 + pgvector with a real vector query (7, 8);
SQLite/PostgreSQL contract parity (9, 15); and a real `prod` E2E in CI (10).

## 11. Honesty note

This document is planning only. No epic is started, no code was changed, and
no test was run. Every code claim above is a file:line reference verified
against the tree at `d07b746` on 2026-08-21; no benchmark, test result, or
performance number is asserted anywhere in this program's documents. Where an
existing document overstates PostgreSQL support, the correction is recorded in
`beta_gap_analysis.md` §2 (G9-G13) and in `docs/feature_matrix.md` rather than
by rewriting history in archived documents.
