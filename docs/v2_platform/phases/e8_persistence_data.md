# E8 — Persistence & Data

**Wave:** Split — E8-S1/E8-S2 (multi-tenant schema + event store) target Alpha;
E8-S3/E8-S4 (artifacts + backup/RPO/RTO) target Beta.
**Status:** In progress · **Stories:** 3/4 complete*. \* E8-S1, E8-S2,
and E8-S3 are complete (see below); E8-S4 is not started (blocked on
E11).
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

**Complete (2026-07-06).** A scoped slice of `E8-S1-T1`/`T2` landed first as
an E7 prerequisite (`decisions/ADR-010-e8s1-scoped-tenancy.md`); the
remainder landed directly against this epic. Summary against the subtasks:

- `E8-S1-T1` (**done**): `tenant_id` + RLS on the *new* E7 tables
  (`code_chunks`, `code_embeddings`) from creation, plus a retrofit onto six
  core tables (sessions/runs/messages/plugins/eval_results/score_snapshots)
  and, as of this pass, `plan_documents`/`plan_approvals`. `run_steps`,
  `plugin_events`, and `score_snapshot_promotions` intentionally keep **no**
  `tenant_id` column of their own — they're scoped transitively via `JOIN`
  to their parent row's tenant_id (see the comment at
  `backend/persistence/migrations/versions.py` lines 14-17). This is by
  design, not a gap.
- `E8-S1-T2` (**done**): `MigrationRunner` supports real `up`/`down` pairs,
  `rollback_to`/`run_down`, verified by an up→down→up round trip
  (`backend/tests/test_tenancy_migrations.py`); both SQLite and Postgres use
  the same versioned runner, including the new plan-tables migration.
- `E8-S1-T3` (**done**): every `SessionRepository`/`RunRepository`/
  `MessageRepository`/`PlanRepository`/`EvalResultRepository`/
  `ScoreSnapshotRepository` method now takes `tenant_id: str =
  DEFAULT_TENANT_ID` (`backend/persistence/base.py`) and both
  `SQLiteStore`/`SQLitePlanStore` and `PostgresStore`/`PostgresPlanStore`
  enforce it (SQLite via `sqlite_tenant_clause()`, Postgres via
  `set_postgres_tenant()` + RLS). The two call sites that invoked these
  Protocols directly (`backend/orchestrator/service.py`,
  `backend/context/providers/session_memory.py`) now pass `tenant_id`
  explicitly; every other caller only touches non-Protocol stores that
  already manage their own tenant scoping.
- `E8-S1-T4` (**done**): SQLite now has full parity with the Postgres RLS
  behavior for every scoped table, including the new plan tables.

DoD check: negative-case tenant-isolation tests added for both adapters
(`backend/tests/test_tenancy_migrations.py`, `test_plan_store.py`); up/down
migrations tested; this doc updated.

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

**Complete (2026-07-16).** Summary against the subtasks:

- `E8-S2-T1` (**done**): `backend/events/store.py` `EventStore` — an
  append-only `events` table persisting every canonical
  :class:`EventEnvelope` (catalog `domain.entity.action` types, E9-S3)
  with a gap-free per-partition `sequence` (`UNIQUE (partition_key,
  sequence)`), `tenant_id`, and the full envelope payload, on both SQLite
  and Postgres. Wired as a wildcard Event Bus subscriber in
  `backend/events/runtime.py:get_event_bus()` behind
  `autodev_event_store_enabled` (default on); the bus's fault-isolated
  dispatch plus a per-thread cached write connection keep the append fast
  and non-blocking for the run (CNF; bounded by the
  `test_flows_checkpoint.py` overhead test).
- `E8-S2-T2` (**done**): flow-state checkpointing itself landed in E3-S3
  (`flow_runs.state_json` + `backend/flows/checkpoint.py`); this story
  adds `EventStore.reconstruct_run()`, rebuilding a run view (status,
  step trail, terminal outcome) purely from stored envelopes, verified
  in test against the `FlowRunStore` record together with a
  `FlowEngine.replay_run()` deterministic-replay assertion (DoD).
- `E8-S2-T3` (**done**): `event_projections` materialization (derived
  status, last sequence/type/time, per-type counts) updated in the same
  transaction as each append — O(1) status queries via
  `get_projection()`/`list_projections()`.
- `E8-S2-T4` (**done**): `EventStore.purge_expired()` compacts events of
  *terminal* partitions older than the configurable retention window
  (`autodev_event_retention_days`, default 30; `-1` disables), always
  keeping the projection row as the compacted summary.

DoD check: reconstruction + deterministic replay covered by
`backend/tests/test_event_store.py`; retention configurable via settings;
event-store docs updated (`docs/feature_matrix.md` § Persistence,
`docs/config.md` env inventory). Record types/DDL/decoders live in
`backend/events/records.py`, mirroring the flows records/state split.

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

**Done (2026-07-16).** Summary against the subtasks:

- `E8-S3-T1` (**done**, landed earlier as E0-S6): `backend/artifacts/store.py`
  — `ArtifactKind`, `ArtifactPointer`, the `ArtifactStore` ABC,
  `LocalArtifactStore`, `MinioArtifactStore`.
- `E8-S3-T2` (**done**): `backend/artifacts/pointers.py` adds
  `ArtifactPointerStore` — a State Store–backed `artifacts` table
  (`UNIQUE (bucket, object_key)`, upsert on re-record) following the
  `EventStore` precedent (`get_store()`, idempotent `_ensure_schema()`,
  SQLite/Postgres shim; zero changes to
  `backend/persistence/postgres_adapter.py`), plus `persist_artifact()`
  to upload and record a pointer in one step. Exported from
  `backend/artifacts/__init__.py`.
- `E8-S3-T3` (**done**): per-tenant, expiring pre-signed URL support added
  to `MinioArtifactStore`/`LocalArtifactStore`.
- `E8-S3-T4` (**done**): `backend/artifacts/cleanup.py` now provides
  `cleanup_unreferenced_artifacts()` — true reference-based GC driven by
  `ArtifactPointerStore.referenced_object_keys()`, keeping the age guard
  via the `autodev_artifact_retention_days` setting (default 7; `-1`
  keeps forever) — exposed as the `artifacts-cleanup --dry-run` CLI
  subcommand.
- Evidence: `backend/tests/test_artifact_pointers.py` (round-trip with
  sha256, tenant isolation, reference-based `persist_artifact`, GC
  preserves referenced / removes orphans / dry-run) — 20 passed together
  with `test_artifact_store.py`; operator docs in `docs/config.md`
  (“Artifact Storage (E8-S3)”).

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
