# E55 — Plan Step State on PostgreSQL

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Done · **Stories:** 3/3
**Depends on:** E49 (persistence contract), E50-S3 (`plan_step_state`
redesign with `tenant_id` and a parent foreign key), E16-S2 (plan step state
machine)
**Enables:** per-step plan approval to work across replicas in the `prod`
profile, and removes the last SQLite file the production profile creates.
**Canonical source:** this document, from a direct read of the current tree
(`d07b746`): `backend/plans/step_state.py:132` falls back to
`./autodev_plan_step_state.db` whenever `DATABASE_URL` is unset **or
PostgreSQL** — the only store in the program that fails silently rather than
loudly.

## Context and problem

The other four ported stores refuse a PostgreSQL URL with a `ValueError`.
`StepApprovalStore` does something worse: it accepts the configuration and
quietly writes plan-step approval state to a SQLite file beside the working
directory. Nothing surfaces the divergence.

Three failures follow. Approval state is invisible to other replicas, so a
step approved on one instance is still pending on another. The file is not in
the `BackupManager` manifest, so it is silently outside backup and restore.
And concurrency is serialized by a process-local `threading.Lock`
(`step_state.py:156`), which provides no protection whatsoever between
processes — the state machine's atomicity guarantee is local to one Python
process.

The table also has no `tenant_id` and no relationship to the plan or session
it describes, which E50-S3 corrects at the schema level.

## Evidence in code

- `backend/plans/step_state.py:114-133` — path resolution; `:128-130` handle
  the two `sqlite://` forms, and `:132` falls through to
  `os.environ.get("AUTODEV_PLAN_STEP_STATE_DB",
  "./autodev_plan_step_state.db")` for everything else, PostgreSQL included.
  The docstring states the deferral outright: per-step approval state "does
  not require extending the PostgreSQL schema/migrations for this story".
- `backend/plans/step_state.py:177` — `sqlite3.connect(str(self._db_path))`.
- `backend/plans/step_state.py:159` — `plan_step_state` created by
  `CREATE TABLE IF NOT EXISTS`, **with no `tenant_id` column** and no foreign
  key to a plan or session.
- `backend/plans/step_state.py:156` — a `threading.Lock` is the only
  serialization; it does not span processes.
- `./autodev_plan_step_state.db` is referenced nowhere else in the
  repository — not in `backend/persistence/backup.py`, so it is absent from
  every backup manifest.
- `backend/persistence/backup.py:66` — the manifest's SQLite component is
  `state_store.sqlite3`, the configured state store only.

## Objective

Move plan step state into the State Store on both backends, give it tenancy
and a parent relationship, replace the process-local lock with database
transactions, migrate any existing file-based state, and delete the fallback
so the `prod` profile creates no SQLite file.

## Key result

In the `prod` profile, step approval works correctly across multiple
replicas, `plan_step_state` lives in PostgreSQL under RLS and inside the
backup manifest, and no `.db` file is created anywhere.

## Scope

- Moving `plan_step_state` into the State Store, both backends.
- Using the `tenant_id` and parent foreign key introduced by E50-S3.
- Preserving the state machine: `draft`, `under_review`, `approved`,
  `rejected`, `executing`, `completed`.
- Atomic transitions, replacing `threading.Lock`.
- Rejecting edit or deletion in illegal states.
- Migrating existing `autodev_plan_step_state.db` data.
- Removing the fallback path and the `AUTODEV_PLAN_STEP_STATE_DB` escape
  hatch, or documenting it as local-only.
- SQLite local-first parity.

## Out of scope

- Changing the state machine itself — E16-S2 defines it and it is preserved
  verbatim.
- The schema migration (E50-S3).
- The broader SQLite → PostgreSQL data migration for other tables (E58);
  this epic migrates only the standalone step-state file, because that file
  is invisible to E58's source database and would otherwise be lost.
- Plan documents and approvals, which already have dual-backend support via
  `SQLitePlanStore` / `PostgresPlanStore`.

## Stories

### E55-S1 — Move step state into the State Store

Subtasks:
- `E55-S1-T1`: move `StepApprovalStore` onto the E49 contract — remove
  `sqlite3.connect`, the private path resolution, and `_create_schema`;
  obtain the connection from the configured State Store.
- `E55-S1-T2`: thread `tenant_id` through every operation using the
  contract's tenant application, and populate the parent reference
  established by E50-S3.
- `E55-S1-T3`: keep SQLite parity so a local-first install continues to work
  against the main `autodev.db` rather than a separate file.

| Criterion | Detail |
| --- | --- |
| Functional | Step state reads and writes go to the configured State Store on both backends |
| Non-functional | No `sqlite3` import remains in `backend/plans/step_state.py`; local installs use the single state store file |
| DoR (specific) | E49-S2 and E50-S3 merged |
| DoD (specific) | Existing step-state tests green on both backends; no separate `.db` file created in either profile |
| Dependencies | E49, E50-S3, E16-S2 |

### E55-S2 — Atomic transitions across replicas

Subtasks:
- `E55-S2-T1`: replace the `threading.Lock` at `step_state.py:156` with the
  E49 transaction primitive, so serialization comes from the database.
- `E55-S2-T2`: make each transition a state-guarded conditional update, so an
  illegal transition fails rather than overwriting — and so two replicas
  cannot both move a step out of `under_review`.
- `E55-S2-T3`: enforce the edit and delete restrictions in illegal states at
  the transition level, and prove them with negative tests.

| Criterion | Detail |
| --- | --- |
| Functional | The six-state machine behaves identically to E16-S2; illegal transitions, edits, and deletes are rejected |
| Non-functional | Serialization is transactional, not process-local; concurrent transitions from two connections yield one winner |
| DoR (specific) | E55-S1 merged |
| DoD (specific) | Concurrency test across two connections; negative tests for each illegal transition |
| Dependencies | E55-S1 |

### E55-S3 — Migrate existing state and remove the fallback

Subtasks:
- `E55-S3-T1`: a migration path for existing `autodev_plan_step_state.db`
  content into the State Store, backfilling `tenant_id` with
  `DEFAULT_TENANT_ID` and resolving the parent reference, reporting rows that
  cannot be resolved rather than dropping them.
- `E55-S3-T2`: delete the fallback at `step_state.py:132` so a PostgreSQL URL
  can never again produce a SQLite file; remove or explicitly document
  `AUTODEV_PLAN_STEP_STATE_DB` as local-only.
- `E55-S3-T3`: assert in test that a `prod`-profile run creates no `.db` file
  in the working directory, and confirm step state is now covered by the
  `BackupManager` manifest.

| Criterion | Detail |
| --- | --- |
| Functional | Existing file-based state is migrated with an explicit report; unresolvable rows are surfaced, not silently dropped |
| Non-functional | No `.db` file is created under `AUTODEV_PROFILE=prod`; step state appears in the backup manifest |
| DoR (specific) | E55-S2 merged |
| DoD (specific) | Migration test from a populated legacy file; no-`.db`-file assertion green |
| Dependencies | E55-S2, E8-S4 (backup manifest) |

## Contracts and decisions

### Architectural decisions required

- No new ADR. E16-S2 defines the state machine and ADR-010 defines the
  tenancy mechanism. The choice of parent entity (plan or session) is made in
  E50-S3's DoR and recorded there; if it changes a `/v2` response shape, that
  is a contract change to record against E16-S2 rather than a new decision.

### Security and multitenancy

- `plan_step_state` has no `tenant_id` today, so approval state is not
  tenant-scoped at all — arguably the program's starkest isolation gap after
  `secrets`. E50-S3 adds the column, E50-S4 adds RLS, and this epic makes
  every operation tenant-scoped through the contract.
- Approval is an authorization decision: a step approved in one tenant must
  never be visible or actionable in another.
- The state-guarded conditional update prevents an approval race from
  promoting a rejected step.

### Migration strategy

- Schema comes from E50-S3, on both backends together.
- Data migration is specific to this epic (E55-S3-T1) because the legacy file
  lives outside the configured `DATABASE_URL` and is therefore invisible to
  E58's source database.
- The migration is idempotent and reports unresolvable rows rather than
  discarding them.

### Compatibility and rollback

- Local-first installs keep working, now against the single state store file
  instead of a second one — an improvement in backup coverage for local users
  as well.
- Rollback is reverting the port; the legacy file is not deleted by the
  migration, so a revert can still read it. State this explicitly in the
  migration output.

## Testing and observability

Tests required:
- Existing step-state suites, green on both backends.
- Two-connection concurrency on transitions.
- Negative tests for each illegal transition, edit, and delete.
- Migration from a populated legacy file, including unresolvable rows.
- Assertion that no `.db` file is created under `prod`.
- Confirmation that step state is present in a backup manifest.
- Tenant isolation on `plan_step_state`.

Observability:
- Step approval events must keep flowing so the E42/E43 execution-visibility
  surfaces stay accurate.
- The migration emits a summary report: rows read, rows written, rows
  unresolved.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Legacy file state lost during the move | Approved steps revert to pending; work repeats | E55-S3-T1 migrates explicitly and reports; the legacy file is retained, not deleted |
| Parent foreign key cannot be resolved for old rows | Migration fails or drops data | Unresolvable rows are reported and retained rather than discarded (E55-S3-T1) |
| `threading.Lock` removed without a transactional replacement | Approval races across replicas | E55-S2-T1 and T2 land together; concurrency test is a DoD gate |
| Fallback removed while some deployment still relies on it | Startup failure after upgrade | Removal happens in the last story, after migration exists; documented in the upgrade notes |
| Local users lose their separate file silently | Confusion about where state went | Migration report plus documentation of the single-file behavior |

## DoR / DoD

- **DoR:** E49-S2 and E50-S3 merged; the parent entity decided; a real
  PostgreSQL available to the test suite.
- **DoD:** all three story DoDs met; step approval works across replicas in
  `prod`; no `.db` file created in `prod`; legacy state migrated with a
  report; step state covered by the backup manifest;
  `docs/v2_platform/progress.md` updated; no push or PR without explicit
  authorization.

## Exit evidence

1. A `prod`-profile run showing an empty working directory — no `.db` file
   created.
2. Two-replica approval test: a step approved on one instance observed as
   approved on the other.
3. Migration report from a populated legacy file: rows read, written,
   unresolved.
4. A backup manifest listing plan step state.

## Affected documents and code

Documents: `docs/v2_platform/progress.md`, `docs/config.md`
(`AUTODEV_PLAN_STEP_STATE_DB` removal or local-only note),
`docs/feature_matrix.md` (plan approval rows),
`docs/v2_platform/e16_s2_plan_state_machine.md`,
`docs/ops/backup_restore.md` (coverage note).

Code: `backend/plans/step_state.py`, `backend/persistence/backup.py`
(manifest coverage confirmation).
