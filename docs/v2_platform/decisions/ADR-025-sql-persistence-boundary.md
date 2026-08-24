# ADR-025: SQL Persistence Boundary and Dialect Abstraction Scope

- **Status:** Accepted
- **Date:** 2026-08-21
- **Authors:** AutoDev platform team
- **Related epic:** E49
- **Supersedes/Relates to:** ADR-001 (PostgreSQL as default production state
  store), ADR-010 (scoped tenancy, `tenant_id` + RLS), E47-S4 (shared
  persistence codecs and adapter split)

## Context

The repository currently holds three different answers to "how does a module
talk to the database", and only one of them is a contract.

The State Store adapters (`backend/persistence/sqlite_adapter/`,
`backend/persistence/postgres_adapter/`) implement the E8 repository
protocols, with pure shared logic in `backend/persistence/codecs.py`. E47-S4
established the boundary explicitly: shared shaping in codecs, SQL text and
dialect details per backend, no ORM, no generic `if postgres` adapter.

Eight further stores implement a second, informal dual-dialect pattern by
hand — a `_is_postgres` flag, `template.format(p="%s" if is_postgres else
"?")`, and a `if not self._is_postgres: conn.execute("BEGIN IMMEDIATE")`
guard — in `backend/flows/state.py:455-469`, `backend/flows/registry.py:117`,
`backend/events/store.py:422-436`, `backend/artifacts/pointers.py:358-372`,
`backend/auth/store.py:409-418`, `backend/plugins/store.py:130-132`,
`backend/plugins/registry_core.py:302-311`, and
`backend/repository/indexing.py:171-174`. The pattern works, but it is copied
rather than shared: a change to transaction or upsert semantics must land in
eight places.

Five domain stores bypass persistence entirely, calling `sqlite3.connect()`
directly and raising `ValueError` on any non-`sqlite://` URL —
`backend/quotas/store.py:70`, `backend/secret_store/store.py:83`,
`backend/execution/policy.py:227`, `backend/environments/store.py:118`, and
`backend/plans/step_state.py:177`, each with its own private
`_resolve_db_path` copy. Because `backend/config/settings.py:332-336`
requires PostgreSQL in the `prod` profile, these five cannot be constructed
in production at all.

Porting those five (E51-E55) without first extracting a contract would mean
writing the eight-fold duplicated pattern five more times.

## Decision

1. **No domain module opens a database connection.** `sqlite3` and `psycopg`
   imports belong to `backend/persistence/` only. Connections are acquired
   through the persistence contract, derived from the configured State Store
   rather than from a private `DATABASE_URL` parse.
2. **A minimal dialect abstraction, scoped to what the codebase already
   uses:** placeholder style, transaction begin/commit/rollback, upserts,
   `RETURNING`, timestamp normalization, row decoding, integrity-error
   mapping to one shared exception type, and tenant application. New
   operations are added when a caller needs them, never speculatively.
3. **No ORM and no query builder.** SQL text stays explicit and readable.
   This restates E47-S4's recorded decision and extends it to domain stores.
4. **Divergence is encapsulated behind named operations, not scattered
   conditionals.** A caller expresses intent — "serialize this critical
   section", "upsert this row" — and the contract chooses the dialect. `if
   postgres` does not appear in method bodies.
5. **Tenant application belongs to the contract**, not to callers. A
   tenant-scoped operation applies `set_postgres_tenant()` on PostgreSQL and
   the `sqlite_tenant_clause()` predicate on SQLite through one call site,
   reusing `backend/persistence/tenancy.py`.
6. **The rule is enforced automatically.** A guard
   (`backend/tests/unit/persistence/test_boundary_guard.py`) AST-scans
   `backend/` — excluding `backend/persistence/` itself, where these
   imports belong by design — for `sqlite3.connect(`/`psycopg.connect(`,
   with an explicit allowlist for the known legitimate exceptions:
   `backend/quotas/migrations.py:137,143` (the read-only tenancy verifier,
   both dialect branches), `backend/ops/doctor.py:119` (the preflight
   connectivity check, deliberately below the persistence layer so a
   health check never constructs a Store or runs migrations as a side
   effect), and each of the five category-3 stores' own `_connect()` — one
   entry per store, naming the story that removes it (E51-E55). The
   allowlist shrinks and never grows silently — a second guard test asserts
   no entry is stale.
7. **SQLite stays first-class.** The contract must not make SQLite a
   degraded path; parity is asserted by the E56 contract suite.

## Alternatives considered

**Adopt an ORM (SQLAlchemy) or a query builder.** Would eliminate dialect
handling wholesale and is the conventional answer. Rejected for three
reasons: E47-S4 already considered and rejected it for the adapters; the
platform depends on hand-written SQL for RLS, `FOR UPDATE`, `ON CONFLICT`,
and pgvector operators that ORMs express awkwardly or not portably; and
introducing one now would mean rewriting both working adapters as a
precondition to fixing five broken stores, inverting the risk profile of an
already-large program.

**Extend the existing `template.format(p=...)` pattern to the five broken
stores.** Cheapest short-term path, and it would work. Rejected because it
would take a pattern already duplicated eight times to thirteen, and each
copy is a place a transaction-semantics fix can be forgotten — precisely the
class of defect this program exists to close.

**A single generic adapter branching on backend internally.** Rejected by
E47-S4 and rejected again here: it concentrates every backend difference into
one module of conditionals, which is harder to reason about than explicit
per-backend SQL and produces exactly the `if postgres` sprawl the design
avoids.

**Leave connection acquisition to callers, share only the dialect helpers.**
Rejected because it preserves the five private `_resolve_db_path` copies and
the possibility of a store choosing its own database file — the specific
mechanism by which `StepApprovalStore` silently writes
`./autodev_plan_step_state.db` in production today.

## Consequences

### Positive

- The five stores that cannot start in `prod` gain a contract to target.
- The dual-dialect pattern is defined once instead of eight times; a
  transaction-semantics fix lands in one place.
- A store can no longer silently choose its own database file.
- Tenant application through a single call site removes a class of isolation
  bug where a caller forgets to scope a query.
- Integrity errors become backend-independent, so callers stop catching
  `sqlite3.IntegrityError` and `psycopg` errors separately.

### Negative / trade-offs

- Migrating eight working stores (E49-S3) is behavior-preserving refactor
  work with regression risk, mitigated only by their existing suites passing
  unmodified.
- One more indirection between a store and its SQL; the abstraction must be
  actively kept minimal or it becomes the ORM this ADR rejects.
- The allowlist is a temporary weakening of the rule and must be watched
  until it empties.

### Contract impact

None on `/v2`. The E8 repository protocols in `backend/persistence/base.py`
are unchanged. This is an internal boundary decision; the contract tests are
the regression net.

## Rollback plan

Each E49 story is a self-contained, behavior-preserving refactor with no data
migration, so rollback is reverting that story's commit; no data risk
attaches to any direction.

The guard (E49-S4) can be disabled independently of the contract if it proves
too noisy, without reverting the contract itself — though doing so removes
the mechanism that prevents the boundary from eroding, and should be recorded
rather than done silently.

## References

- `backend/persistence/contract.py` (the implementation), `backend/persistence/base.py`,
  `backend/persistence/codecs.py`, `backend/persistence/database.py:20-40`,
  `backend/persistence/tenancy.py`,
  `backend/tests/unit/persistence/test_boundary_guard.py` (the guard)
- `backend/quotas/store.py:41-70`, `backend/secret_store/store.py:40-83`,
  `backend/execution/policy.py:198-227`,
  `backend/environments/store.py:30-118`,
  `backend/plans/step_state.py:114-177`
- `backend/config/settings.py:332-336`
- `docs/v2_platform/phases/e47_backend_structural_consolidation.md` (E47-S4)
- `docs/v2_platform/phases/e49_shared_sql_infrastructure.md`
- `docs/v2_platform/postgres_production_completeness.md`
