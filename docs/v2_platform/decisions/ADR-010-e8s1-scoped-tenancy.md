# ADR-010: Scoped E8-S1 Tenancy Slice for E7 (Down Migrations + tenant_id/RLS)

- **Status:** Accepted
- **Date:** 2026-07-06
- **Authors:** AutoDev Team
- **Related epic:** E7 (Context & RAG), prerequisite slice of E8 (Persistence & Data)
- **Supersedes/Relates to:** ADR-001 (PostgreSQL as Default Production State Store)

## Context

E7 (Context & RAG) needs its new tables — `code_chunks` (E7-S1) and
`code_embeddings` (E7-S2) — to be tenant-scoped from day one: indexed
repository content and embeddings must not leak across tenants once
multi-tenancy lands, and retrofitting isolation onto a vector store after the
fact is far more disruptive than building it in from the start. That need is
exactly the subject of **E8-S1 — Multi-tenant data model and migrations**,
which per `docs/v2_platform/phases/e8_persistence_data.md` covers: (1) a
tenant_id + Row-Level Security (RLS) schema for sessions/runs/steps/entities,
(2) a versioned migration framework with up/down reversibility, (3) a
repository layer with *mandatory* tenant scoping at every call site, and (4) a
SQLite local profile with schema parity.

E8-S1 has not started, and E8 as a whole is not in this epic's scope. Doing
the full story here would mean rewriting every repository method's call
sites across the app (sessions, runs, messages, plugins, evals, snapshots,
flows, plans, ...) to require and thread a tenant argument — a large,
cross-cutting change with its own review surface, unrelated to shipping
Context & RAG. Blocking E7 on that full rewrite is not a reasonable
trade-off; conversely, building E7's vector/chunk tables *without* any
tenancy story at all would be actively harmful (silent cross-tenant leakage
baked into a brand-new subsystem).

## Decision

Implement a **deliberately scoped slice** of E8-S1 as an E7 prerequisite,
landing exactly what E7 needs and no more:

1. **`backend/persistence/tenancy.py`** — `DEFAULT_TENANT_ID` plus two small
   helpers: `set_postgres_tenant()` (sets the `app.tenant_id` RLS session
   variable via parameter-safe `set_config(...)`, not a literal `SET LOCAL`
   string) and `sqlite_tenant_clause()` (a SQLite-side `WHERE`-fragment
   helper, since SQLite has no RLS equivalent).
2. **Down-migration support** in `backend/persistence/migrations/runner.py` —
   `Migration(up, down)` pairs, `rollback_to(version)`, and `run_down(steps)`,
   fully backward compatible with the existing forward-only migration lists
   (a bare callable is wrapped with a documented no-op `down`).
3. **`tenant_id` + RLS on the *new* E7 tables** (`code_chunks` in E7-S1,
   `code_embeddings` in E7-S2) — this is the load-bearing part E7 actually
   needs, done as `Migration` entries with real `up`/`down` steps from the
   start.
4. **A lighter `tenant_id` column retrofit** on the existing core tables
   (`sessions`, `runs`, `messages`, `plugins`, `eval_results`,
   `score_snapshots`), defaulted to `'default'` for every existing row, plus
   RLS policies on PostgreSQL. Child/audit tables (`run_steps`,
   `plugin_events`, `score_snapshot_promotions`) are scoped transitively
   through their parent row and are not retrofitted directly.
5. **PostgresStore now uses the same versioned `MigrationRunner`** as
   `SQLiteStore` (`backend/persistence/migrations/postgres_versions.py`),
   replacing the prior ad hoc `CREATE TABLE IF NOT EXISTS` block, so both
   backends share one migration mental model and Postgres migrations are
   reversible too.

## What is explicitly deferred to a future, full E8-S1 story

- **Mandatory tenant scoping at every repository call site.** No existing
  `PostgresStore`/`SQLitePlanStore`/etc. method signature changes to require
  a tenant argument; callers keep working unscoped (implicitly `'default'`).
  A full E8-S1 pass must thread tenant context through the repository layer
  and its callers (API routers, orchestrator, flows) end to end.
- **`run_steps`, `plugin_events`, `score_snapshot_promotions`** and any other
  child/audit tables — not retrofitted with their own `tenant_id` column.
- **Entities/steps schema beyond what already exists**, and any tenant
  provisioning/management API — out of scope here.
- **E8-S2/S3/S4** (event store, Artifact Store, backup/RPO/RTO) — untouched;
  this ADR is scoped to E8-S1 only, and only a slice of it.

`docs/v2_platform/progress.md` and `phases/e8_persistence_data.md` record E8
as still "Not started" with a note pointing here, rather than marking E8-S1
"Done" — the DoD in the phase doc (repository coverage >= 85% with mandatory
tenant filtering, negative-case RLS tests across the full repository layer)
is intentionally not claimed by this slice.

## Alternatives considered

1. **Do nothing tenancy-related for E7; add it later.** Rejected — retrofitting
   RLS onto an already-populated vector/chunk store is riskier and more
   disruptive than building it in from the start, and the reference
   architecture (§18.7.1) lists E8 as an E7 dependency for exactly this reason.
2. **Implement the full E8-S1 story now.** Rejected for this task — it is a
   large, separately reviewable change (repository-wide call-site rewrite)
   that would roughly double the size of this already-large epic and delay
   Context & RAG delivery without a corresponding benefit to E7 itself.
3. **Application-level tenant filtering only (no Postgres RLS).** Rejected —
   RLS gives a fail-closed, defense-in-depth guarantee (a forgotten `WHERE
   tenant_id = ...` in application code does not leak rows) that pure
   application-level filtering cannot provide by itself; RLS is cheap to add
   at table-creation time and expensive to retroactively bolt on.

## Consequences

- **Positive:** E7's new tables ship tenant-safe from day one; the migration
  framework gains real reversibility (previously forward-only), benefiting
  every future story that touches schema; PostgresStore and SQLiteStore now
  share one migration abstraction.
- **Negative / trade-offs:** E8 remains "Not started" as an epic — this ADR
  does not close it, and a future story must still do the full repository
  rewrite. The core tables carry an unused-by-most-code `tenant_id` column
  until that rewrite lands (harmless: defaulted, indexed implicitly via the
  RLS policy predicate, not yet queried by application code).
- **Contract impact:** Additive migrations only (new column, new table
  policies); no existing migration is edited or reordered. `MigrationRunner`
  gains new methods (`rollback_to`, `run_down`) and an `engine` parameter
  with a backward-compatible default (`"sqlite"`); existing call sites are
  unchanged.

## Rollback plan

Every migration added by this slice has a real `down` step (dropping the
policy, disabling RLS, dropping the column) verified by an up→down→up round
trip test (`backend/tests/test_tenancy_migrations.py`, run against a real
temporary SQLite file, plus DDL-shape assertions against the existing
`FakeConnection`/`FakeCursor` Postgres mock). `MigrationRunner.rollback_to`/
`run_down` can be invoked to revert to any prior schema version.

## References

- `docs/v2_platform/phases/e8_persistence_data.md` (E8-S1 full scope)
- `docs/v2_platform/phases/e7_context_rag.md` (E7-S1/E7-S2 dependency on E8)
- ADR-001 (PostgreSQL as Default Production State Store)
- `backend/persistence/tenancy.py`, `backend/persistence/migrations/runner.py`,
  `backend/persistence/migrations/postgres_versions.py`
