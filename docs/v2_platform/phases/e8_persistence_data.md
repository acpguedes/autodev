# E8 — Persistence & Data

**Wave:** Split — E8-S1/E8-S2 (multi-tenant schema + event store) target Alpha;
E8-S3/E8-S4 (artifacts + backup/RPO/RTO) target Beta.
**Status:** Not started · **Stories:** 1/4 complete* (matches
`../progress.md`'s epic table). \* A scoped E8-S1 slice — tenant_id + RLS on
new/core tables, reversible up/down migrations — landed as an E7 prerequisite
(`decisions/ADR-010-e8s1-scoped-tenancy.md`); it is **not** a fully-DoD'd
E8-S1 story (see the note under E8-S1 below), so the epic Status stays "Not
started" rather than "In progress".
**Depends on:** E0
**Enables:** durable base for E3, E9, E11; integrates with E11 (backup)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.7.2 (E8), §18.8, §18.9

## Objective

Establish the durable **multi-tenant** data model in the **State Store
(PostgreSQL)**, with versioned migrations, an **event store**, integration with the
**Artifact Store (MinIO)**, and SQLite support for local mode.

## Key result

Sessions, runs, steps, and entities persist consistently and isolated per tenant, with
RPO <= 5 min and reversible migrations; large artifacts live in MinIO referenced by
metadata.

## Stories

### E8-S1 — Multi-tenant data model and migrations

**Partial progress (2026-07-06):** a scoped slice of `E8-S1-T1` and
`E8-S1-T2` landed as an E7 prerequisite —
`decisions/ADR-010-e8s1-scoped-tenancy.md` records exactly what shipped and
what was deferred. Summary against the subtasks below:

- `E8-S1-T1` (**partial**): `tenant_id` + RLS added to the *new* E7 tables
  (`code_chunks`, `code_embeddings`) from creation, plus a retrofit onto six
  core tables (sessions/runs/messages/plugins/eval_results/score_snapshots).
  Not done: `run_steps`/`plugin_events`/`score_snapshot_promotions` and any
  other entities/steps tables.
- `E8-S1-T2` (**done** for the migrations this slice touched): `MigrationRunner`
  now supports real `up`/`down` pairs, `rollback_to`/`run_down`, verified by
  an up→down→up round trip against a real temp SQLite file
  (`backend/tests/test_tenancy_migrations.py`); `PostgresStore` moved from ad
  hoc `CREATE TABLE IF NOT EXISTS` to the same versioned runner.
- `E8-S1-T3` (**not done**): no repository call site was changed to require
  a tenant argument; every existing method keeps its current signature and
  implicitly operates on the `'default'` tenant. This is the largest
  remaining piece of E8-S1.
- `E8-S1-T4` (**not done** beyond what already existed): no new SQLite
  parity work beyond the `tenant_id` column retrofit above.

Subtasks:
- `E8-S1-T1`: sessions/runs/steps/entities schema with `tenant_id` and Row-Level Security (RLS).
- `E8-S1-T2`: versioned migration framework (up/down) with reversibility checks.
- `E8-S1-T3`: repository layer with mandatory tenant scoping.
- `E8-S1-T4`: local SQLite profile with essential schema parity.

| Item | Content |
| --- | --- |
| CF | Every read/write is tenant-filtered; migrations apply and roll back; SQLite runs the local-first core |
| CNF | No cross-tenant query without scope; migration reversible when possible; repository coverage >= 85% |
| DoR | E0 done; logical model reviewed in an ADR; tenancy policy defined |
| DoD | RLS tested with negative cases; migration tested in CI up->down->up; data-model docs |
| Dependencies | E0 |

### E8-S2 — Event Store and run durability

Subtasks:
- `E8-S2-T1`: append-only events table (`domain.entity.action`) ordered per run.
- `E8-S2-T2`: flow-state checkpointing for deterministic replay.
- `E8-S2-T3`: projections/materializations for fast status queries.
- `E8-S2-T4`: event retention and compaction policy.

| Item | Content |
| --- | --- |
| CF | Every step emits persisted events; a run can be reconstructed from the event store; projections reflect current state |
| CNF | Event write does not block the run (fast append); deterministic replay; RPO <= 5 min |
| DoR | E8-S1 ready; event catalog aligned with E9 |
| DoD | Replay reproduces an identical run in test; configurable retention; event-store docs |
| Dependencies | E8-S1, E3 (Orchestration Engine), E9 (event catalog) |

### E8-S3 — Artifact Store (MinIO)

Subtasks:
- `E8-S3-T1`: S3-compatible client for patches, logs, outputs, and builds.
- `E8-S3-T2`: artifact reference by metadata in the State Store (no binaries in the DB).
- `E8-S3-T3`: pre-signed URLs scoped and expiring per tenant.
- `E8-S3-T4`: lifecycle/cleanup of orphaned artifacts.

| Item | Content |
| --- | --- |
| CF | Artifacts written/read by reference; download via pre-signed URL; per-tenant bucket/prefix isolation |
| CNF | No large binaries in PostgreSQL; configurable URL expiration; checksum integrity |
| DoR | E8-S1 ready; MinIO provisioned; retention policy defined |
| DoD | Upload/download tested; orphan cleanup scheduled; artifact docs |
| Dependencies | E8-S1 |

### E8-S4 — Backup, RPO/RTO, and reversibility

Subtasks:
- `E8-S4-T1`: logical/physical backup of PostgreSQL and MinIO.
- `E8-S4-T2`: restore runbook with RTO <= 30 min verification.
- `E8-S4-T3`: automated periodic restore test.

| Item | Content |
| --- | --- |
| CF | Backup is schedulable; restore is documented and executable; post-restore integrity check |
| CNF | RPO <= 5 min, RTO <= 30 min in production; restore test in CI/staging |
| DoR | E8-S1..S3 ready; staging environment available |
| DoD | End-to-end restore validated; runbook published; backup-failure alerts |
| Dependencies | E8-S1, E8-S2, E8-S3, E11 |

## v1 precursor / starting point

- A `Store`/repository abstraction, a SQLite adapter, and a versioned migration runner
  (`schema_version` table + ordered migration callables) are already `default`
  (`backend/persistence/`) — direct precursor to E8-S1's SQLite/migration side.
  `PostgresStore` is a `stub` (`NotImplementedError`), `RedisJobQueue` is a `stub`,
  and MinIO integration is `planned` — see `docs/feature_matrix.md` § Persistence.
- There is no multi-tenant model, no RLS, and no event store today; E8-S1's tenancy
  work and all of E8-S2 start from zero.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [ ] Contract tests green for the repository layer and event-store read/write paths.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Alpha exit criterion "multi-tenant schema + event store" (E8-S1/E8-S2) and Beta
      entry item "artifacts + backup/RPO/RTO" (E8-S3/E8-S4) satisfied per §18.9.
