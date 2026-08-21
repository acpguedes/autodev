# E49 — Shared SQL Persistence Infrastructure

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/4
**Depends on:** E8 (repository protocols, `get_store()`), E47-S4 (shared
codecs and the per-backend adapter split that established the boundary rule)
**Enables:** E50-E55 — the five stores that currently refuse a PostgreSQL URL
can only be ported once there is a persistence contract for them to target.
Without this epic each port would hand-roll its own dialect handling and the
duplication would grow from five copies to ten.
**Canonical source:** this document, from a direct read of the current tree
(`d07b746`): five domain stores call `sqlite3.connect()` directly and each
carries its own private `_resolve_db_path` copy, while eight other stores
already implement a second, informal dual-dialect pattern
(`template.format(p="%s" if is_postgres else "?")`).

## Context and problem

The repository has three different answers to "how do I talk to the
database", and only one of them is a contract.

1. **The State Store adapters** (`sqlite_adapter/`, `postgres_adapter/`)
   implement the E8 repository protocols with shared pure logic in
   `backend/persistence/codecs.py`. This is the intended design and E47-S4
   made it explicit: shared shaping in codecs, SQL text and dialect details
   per backend.
2. **Eight "dual-dialect" stores** (flows, events, auth, artifacts, plugins)
   each re-implement the same informal pattern by hand: a `_is_postgres`
   flag, `template.format(p=...)` placeholder substitution, and a
   `if not self._is_postgres: conn.execute("BEGIN IMMEDIATE")` guard. The
   pattern works, but it is copied, not shared — a fix to transaction or
   upsert semantics must land in eight places.
3. **Five domain stores** bypass persistence entirely, calling
   `sqlite3.connect()` and raising `ValueError` on anything that is not a
   `sqlite://` URL.

Category 3 is what breaks production, and it is the subject of E51-E55. But
porting those five without first extracting a contract would mean writing the
category-2 pattern five more times. This epic creates the contract, proves it
by migrating the existing category-2 stores onto it, and closes the door
architecturally so category 3 cannot reappear.

## Evidence in code

Stores bypassing the persistence layer (each with its own `_resolve_db_path`):

| Store | `sqlite3.connect` | Private path resolver | Rejects PostgreSQL |
| --- | --- | --- | --- |
| `QuotaStore` | `backend/quotas/store.py:70` | `:41` | `:49` raises `ValueError` |
| `SecretStore` | `backend/secret_store/store.py:83` | `:40` | `:48` raises `ValueError` |
| `PolicyStore` | `backend/execution/policy.py:227` | `:198` | `:206` raises `ValueError` |
| `EnvironmentStore` | `backend/environments/store.py:118` | `:31` | `:38` raises `ValueError` |
| `StepApprovalStore` | `backend/plans/step_state.py:177` | `:114` | `:132` silent fallback |

The duplicated dual-dialect pattern:
- `backend/flows/state.py:455-469` and `backend/flows/schema_sql.py:6`
  (`flow_state_statements(is_postgres)`).
- `backend/flows/registry.py:117,167-190` (two DDL branches at `:176`/`:187`).
- `backend/events/store.py:422-436` and `backend/events/records.py:43`.
- `backend/artifacts/pointers.py:36,358-372`.
- `backend/auth/store.py:409-418` and `backend/auth/migrations.py:12`.
- `backend/plugins/store.py:130-132`;
  `backend/plugins/registry_core.py:138,168,199,302-311`.
- `backend/repository/indexing.py:171-174` (`_param_style()`).

SQLite-specific transaction syntax that has no PostgreSQL counterpart:
- `BEGIN IMMEDIATE` at `backend/quotas/store.py:166,218,310,389,435` and
  `backend/secret_store/store.py:140,188,241`.
- `INSERT OR IGNORE` at `backend/quotas/store.py:391,437`.
- `backend/quotas/store.py:6-8` documents a
  `SELECT ... FOR UPDATE` PostgreSQL path — **`FOR UPDATE` does not appear
  anywhere in the repository.** The docstring describes an unimplemented
  design.

Connection handling:
- `backend/persistence/database.py:26-40` — `get_store()` is the only
  URL-based backend switch; `:23` aliases `DurableStore = SQLiteStore`
  unconditionally, independent of the configured URL.
- `backend/persistence/postgres_adapter/_shared.py:10-28` — a fresh
  `psycopg.connect` per operation (pooling is E60).

## Objective

Give domain stores one persistence contract to depend on — connection
acquisition from the configured State Store plus a minimal dialect
abstraction — so that a store is written once and runs on both backends, and
so that `sqlite3` and `psycopg` stop appearing in domain code.

## Key result

Domain stores depend on a persistence contract rather than on `sqlite3` or
`psycopg` directly; the placeholder/transaction/upsert pattern that is
currently copied across eight modules is defined once; and an automated guard
prevents a new store from calling `sqlite3.connect()` outside
`backend/persistence/`.

## Scope

- Connection acquisition routed through the configured State Store.
- A minimal dialect abstraction covering exactly what the codebase needs:
  `?`/`%s` placeholders, transaction begin/commit/rollback, upserts,
  `RETURNING`, timestamp handling, row decoding, integrity-error mapping,
  and tenant application.
- A transaction/locking primitive expressing the intent behind
  `BEGIN IMMEDIATE` (SQLite) and `SELECT ... FOR UPDATE` (PostgreSQL).
- Migration of the eight existing dual-dialect stores onto the contract.
- The architectural rule and its automated guard.

## Out of scope

- **No ORM and no query builder.** SQL text stays explicit and readable, per
  the decision already recorded for E47-S4. ADR-025 restates and scopes it.
- No generic `if postgres` mega-adapter — divergence is encapsulated behind
  named operations, not scattered as conditionals.
- Porting the five category-3 stores (E51-E55) and creating their PostgreSQL
  schema (E50).
- Connection pooling, timeouts, and retry (E60).
- Changing the E8 repository protocols or any `/v2` contract.

## Stories

### E49-S1 — Persistence contract and dialect abstraction

Subtasks:
- `E49-S1-T1`: define the contract in `backend/persistence/` — connection
  acquisition derived from the configured store rather than from a private
  `DATABASE_URL` parse, removing the need for five copies of
  `_resolve_db_path`.
- `E49-S1-T2`: define the dialect surface: placeholder style, upsert form,
  `RETURNING` support, timestamp normalization, and integrity-error mapping
  to one shared exception type so callers stop catching backend-specific
  errors.
- `E49-S1-T3`: fold tenant application into the contract so a tenant-scoped
  operation applies `set_postgres_tenant()` on PostgreSQL and the
  `sqlite_tenant_clause()` predicate on SQLite through one call site, reusing
  `backend/persistence/tenancy.py` rather than duplicating it.

| Criterion | Detail |
| --- | --- |
| Functional | An operation written once against the contract executes correctly on both backends |
| Non-functional | The dialect surface covers only operations the codebase actually uses; no ORM, no query builder; SQL text remains explicit |
| DoR (specific) | ADR-025 drafted |
| DoD (specific) | Unit tests exercising each dialect operation on both backends |
| Dependencies | E8, E47-S4 |

### E49-S2 — Transaction and locking primitive

Subtasks:
- `E49-S2-T1`: express the serialization intent currently written as
  `BEGIN IMMEDIATE` as a named primitive that maps to `BEGIN IMMEDIATE` on
  SQLite and to an explicit transaction with row-level locking on
  PostgreSQL.
- `E49-S2-T2`: provide the row-lock operation (`SELECT ... FOR UPDATE`) the
  quota and secret ports need — the operation `backend/quotas/store.py:6-8`
  claims exists but does not; delete the false docstring claim as part of
  this subtask.
- `E49-S2-T3`: move row decoding onto the shared codecs module so both
  backends return the same shapes, extending `backend/persistence/codecs.py`
  rather than adding a parallel module.

| Criterion | Detail |
| --- | --- |
| Functional | A critical section written once serializes correctly on both backends; rollback restores pre-transaction state |
| Non-functional | No caller writes `BEGIN IMMEDIATE` or `FOR UPDATE` directly; docstrings describe implemented behavior only |
| DoR (specific) | E49-S1 merged |
| DoD (specific) | Concurrency test proving mutual exclusion on both backends, and a rollback test |
| Dependencies | E49-S1 |

### E49-S3 — Migrate the existing dual-dialect stores

Subtasks:
- `E49-S3-T1`: move the flow stores (`flows/state.py`,
  `flows/schema_sql.py`, `flows/registry.py`) onto the contract, deleting
  their local `template.format(p=...)` and `_is_postgres` handling.
- `E49-S3-T2`: same for `events/store.py` + `events/records.py`,
  `artifacts/pointers.py`, and `auth/store.py` + `auth/migrations.py`.
- `E49-S3-T3`: same for `plugins/store.py`, `plugins/registry_core.py`, and
  `repository/indexing.py:171-174`.

Migrating these first is what proves the contract against real, already-
working dual-backend code before E51-E55 depend on it.

| Criterion | Detail |
| --- | --- |
| Functional | Behavior byte-identical; the existing suites for flows, events, auth, artifacts, and plugins pass unmodified |
| Non-functional | The placeholder/transaction pattern exists in one module instead of eight; per-thread connection caching in `auth/store.py:419-429` and `artifacts/pointers.py` is preserved or explicitly superseded |
| DoR (specific) | E49-S2 merged |
| DoD (specific) | All eight stores' suites green with the shared contract underneath; no `template.format(p=` remaining in domain code |
| Dependencies | E49-S1, E49-S2 |

### E49-S4 — Persistence boundary rule and guard

Subtasks:
- `E49-S4-T1`: record the rule in ADR-025 — no domain module opens a
  database connection directly; `sqlite3` and `psycopg` imports belong to
  `backend/persistence/` only.
- `E49-S4-T2`: add an automated guard (test or lint rule) asserting no
  `sqlite3.connect(` or `psycopg.connect(` outside
  `backend/persistence/`, with an explicit, documented allowlist for the
  known legitimate exceptions — `backend/persistence/backup.py:270,272,555,557`
  (SQLite snapshot/restore) and `backend/quotas/migrations.py:143` (the
  read-only tenancy verifier) until each is migrated.
- `E49-S4-T3`: resolve the `DurableStore = SQLiteStore` alias at
  `backend/persistence/database.py:23`, which returns SQLite regardless of
  the configured URL and is consumed by `backend/sdk/testing.py:30` — either
  make it URL-aware or rename it so its SQLite-only nature is explicit.

| Criterion | Detail |
| --- | --- |
| Functional | A new store cannot open its own SQLite connection without failing the guard |
| Non-functional | The allowlist is explicit and shrinks as E51-E55 land; no silently permitted exceptions |
| DoR (specific) | E49-S3 merged (the guard would otherwise fail on code this epic is still migrating) |
| DoD (specific) | Guard test green; ADR-025 `Accepted`; allowlist documented with the story that removes each entry |
| Dependencies | E49-S3 |

## Contracts and decisions

### Architectural decisions required

- **ADR-025 — SQL persistence boundary**
  (`decisions/ADR-025-sql-persistence-boundary.md`, `Proposed`): the boundary
  rule, the scope of the dialect abstraction, and the explicit no-ORM stance.
  Decided within E49-S1/S4.
- No new `/v2` contract surface; this epic is internal.

### Security and multitenancy

- Tenant application must move *into* the contract (E49-S1-T3), not remain a
  caller responsibility — a store that forgets `set_postgres_tenant()` on
  PostgreSQL silently reads across tenants under `FORCE ROW LEVEL SECURITY`
  only because the policy denies rows; on SQLite a forgotten predicate leaks
  data outright.
- The contract must not cache a connection with tenant state set; RLS
  session-state safety on reuse is E60-S2, and until then connections stay
  per-operation.

### Migration strategy

- No schema change in this epic. Existing tables and migrations are
  untouched.
- Store migration is incremental and behavior-preserving, one group per
  story, each independently revertible.

### Compatibility and rollback

- SQLite remains the local-first default; the contract must not make SQLite a
  second-class path.
- Each story is a self-contained refactor; rollback is reverting that story's
  commit. No data migration is involved, so rollback carries no data risk.

## Testing and observability

Tests required:
- Dialect operations on both backends (placeholders, upsert, `RETURNING`,
  timestamps, integrity-error mapping).
- Mutual exclusion and rollback for the transaction primitive on both
  backends.
- The eight migrated stores' existing suites, unmodified — they are the
  regression net.
- The boundary guard itself.

Observability:
- No new metrics. Query, pool, and lock metrics are E60-S4.
- Integrity-error mapping should preserve enough context to keep existing log
  messages meaningful.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| The abstraction grows into a de-facto ORM | The over-abstraction E47 explicitly warned against | ADR-025 fixes the scope to operations already present in the codebase; SQL text stays explicit (E49-S1-T2) |
| Migrating eight working stores introduces regressions | Breakage in flows, auth, events | Their existing suites must pass unmodified; migrate in three separate stories, not one |
| Tenant application changes alter isolation behavior | Cross-tenant read | Reuse `tenancy.py` primitives unchanged; isolation tests stay green |
| The guard's allowlist becomes permanent | The rule erodes | Each allowlist entry names the story that removes it (E49-S4-T2) |

## DoR / DoD

- **DoR:** ADR-025 drafted; the duplicated pattern inventory above confirmed
  against the tree at implementation time.
- **DoD:** all four story DoDs met; the eight migrated stores' suites green
  unmodified; the boundary guard active with a documented, shrinking
  allowlist; ADR-025 `Accepted`; `docs/v2_platform/progress.md` updated; no
  push or PR without explicit authorization.

## Exit evidence

1. Test output for the eight migrated stores, unmodified suites.
2. The boundary guard failing on a deliberately added
   `sqlite3.connect()` in a domain module, and passing once removed.
3. Concurrency test output showing mutual exclusion on both backends.
4. ADR-025 at `Accepted`.

## Affected documents and code

Documents: `docs/v2_platform/progress.md`,
`decisions/ADR-025-sql-persistence-boundary.md`, `decisions/README.md`,
`docs/feature_matrix.md` (store-abstraction row).

Code: `backend/persistence/` (contract, dialect, codecs, database.py),
`backend/flows/{state,schema_sql,registry}.py`,
`backend/events/{store,records}.py`, `backend/artifacts/pointers.py`,
`backend/auth/{store,migrations}.py`,
`backend/plugins/{store,registry_core}.py`,
`backend/repository/indexing.py`, `backend/sdk/testing.py`,
`backend/quotas/store.py` (docstring correction only in this epic).
