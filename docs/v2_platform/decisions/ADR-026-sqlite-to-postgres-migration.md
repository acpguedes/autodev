# ADR-026: SQLite to PostgreSQL Migration and Cutover

- **Status:** Accepted
- **Date:** 2026-08-21 (accepted 2026-08-27)
- **Authors:** AutoDev platform team
- **Related epic:** E58
- **Supersedes/Relates to:** ADR-001 (PostgreSQL as default production state
  store), ADR-014 (secret store format), ADR-025 (SQL persistence boundary)

## Context

Reference §4.6 states that upgrading between deployment modes is "progressive
and without rewriting", and that swapping SQLite for PostgreSQL "is a
configuration change, not a code change". For schema, that is true:
`autodev upgrade` (`backend/ops/upgrade.py:85`) backs up and then migrates a
store's schema forward.

For data, nothing implements it. Changing `DATABASE_URL` from `sqlite://` to
`postgresql://` starts an empty database — sessions, runs, messages, plans,
quotas, secrets, and policies all appear to vanish. There is no `database`
CLI namespace and no `migrate` command (`backend/cli.py:64`, `:260-274`), no
Makefile target, and no documented procedure. An operator attempting the move
must write their own migration and has no way to verify it moved everything.

Two properties make this harder than a table copy. Secrets are stored as
ciphertext (`backend/secret_store/store.py:91`) and must cross unchanged;
re-encrypting or double-encrypting them would render every credential
unusable. And plan step state lives in a *separate* SQLite file outside
`DATABASE_URL` (`backend/plans/step_state.py:132`), invisible to any migrator
that reads only the configured source database.

Once a migration path exists, the question of how to cut over follows
immediately, and the tempting answer — write to both databases during a
transition — has consequences worth deciding deliberately rather than
discovering.

## Decision

1. **Migration is one-way: SQLite to PostgreSQL.** No reverse migration is
   provided. Rollback is returning to the untouched source, not migrating
   back.
2. **The source database is never mutated.** The migrator reads a consistent
   snapshot and writes only to the destination. The standalone step-state
   file is likewise retained, not deleted.
3. **A dedicated operator command**, `autodev database migrate --from ...
   --to ...`, registered through the existing `backend/cli_plugins/`
   auto-discovery contract (`backend/cli_plugins/__init__.py:23-52`). It is
   an operator task and is never exposed through the API — the migrator
   necessarily operates across tenants, so RLS cannot constrain it.
4. **Preflight and dry run are mandatory capabilities.** Both URLs reachable,
   destination schema version equal to the source's, destination empty or
   explicitly confirmed, required extensions present, and the standalone
   step-state file detected and reported when present. `--dry-run` reports
   exactly what would move and writes nothing.
5. **The destination schema is created by the normal migration runner**, not
   by the migrator. The migrator moves data; it does not define schema.
6. **Identity is preserved and sequences are adjusted.** Primary keys and
   cross-table identifiers cross unchanged, and sequences are advanced past
   the migrated maximum so newly generated identifiers cannot collide — the
   classic post-migration defect.
7. **The migrator never decrypts.** Secret ciphertext is carried
   byte-for-byte. Re-encrypting during migration would place plaintext in the
   migrator's memory and risk making every credential unusable.
8. **`tenant_id` is preserved exactly.** Rows with no tenant map explicitly
   to `DEFAULT_TENANT_ID` and are counted in the report. A migrator that
   defaulted tenants silently would merge tenants.
9. **Reconciliation is a gate, not a warning.** Per-table row counts and
   content hashes are compared between source and destination; a mismatch
   fails the migration. The report is persisted as a file so it can be
   attached to a change record, and it is the artifact an operator uses to
   decide whether to cut over.
10. **The migration is resumable and idempotent.** An interrupted run resumes
    without duplication; a completed run re-executed is a no-op.
11. **Permanent dual-write is prohibited.** Cutover happens in a documented
    maintenance window: the source becomes read-only, the migration runs,
    reconciliation passes, the destination is verified, and only then does it
    accept traffic.

## Alternatives considered

**Dual-write during a transition window, for zero downtime.** The obvious way
to avoid a maintenance window. Rejected: it requires a conflict-resolution
model the platform does not have, and it makes "which database is
authoritative" ambiguous at exactly the moment an operator most needs
certainty. A bounded, documented maintenance window is the honest trade for a
self-hostable platform whose typical deployment is a single tenant-operator.

**Logical replication or a foreign-data-wrapper copy.** Powerful, and the
right answer at much larger scale. Rejected as disproportionate: it adds
PostgreSQL operational surface for a one-time promotion, and it does not
address the two genuinely awkward parts — the out-of-band step-state file and
ciphertext handling — which need application knowledge either way.

**Backup-and-restore as the migration mechanism.** Attractive because
`BackupManager` already handles both engines. Rejected because its SQLite and
PostgreSQL components are separate snapshots of the same logical data, not a
cross-engine conversion; restoring a SQLite snapshot into PostgreSQL is not
something the manifest format expresses.

**No tool; document a manual procedure.** Rejected: without reconciliation an
operator cannot know the move was complete, and silent partial migration is
the worst available outcome.

**Support bidirectional migration.** Rejected as unjustified scope. The
supported downgrade path is to stop using the PostgreSQL destination and
return to the retained source.

## Consequences

### Positive

- The local-first promise gains an implementation: an existing installation
  can be promoted with verifiable completeness.
- The move becomes rehearsable — dry run first, reconcile, then decide.
- Rollback is trivially safe because the source is never touched.
- Secrets and step state, the two easiest things to lose, are handled
  explicitly rather than by assumption.

### Negative / trade-offs

- Cutover requires a maintenance window; zero-downtime promotion is not
  offered.
- Both databases must be at the same schema version, so an operator on an old
  version must upgrade before migrating — enforced by preflight rather than
  discovered mid-migration.
- The migrator holds cross-tenant read access by nature, which is why it is
  restricted to an operator CLI and excluded from the API surface.

### Contract impact

Adds a `database migrate` CLI command. No `/v2` API change. `autodev upgrade`
keeps its existing schema-only meaning; the relationship between the two
commands is documented so operators do not confuse them.

## Rollback plan

Point `DATABASE_URL` back at the SQLite source, which the migration never
modified, and restart. The retained step-state file remains readable by the
pre-E55 code path.

If the migration fails partway, the destination is discarded and recreated
rather than repaired by hand — the source is authoritative until
reconciliation passes and cutover completes.

## References

- `backend/ops/upgrade.py:85, :113-126`
- `backend/cli.py:64, :260-274`; `backend/cli_plugins/__init__.py:23-52`
- `backend/persistence/database.py:26-40`
- `backend/secret_store/store.py:91`; `backend/plans/step_state.py:132`
- `backend/artifacts/pointers.py`
- `docs/architecture/v2_platform_reference.md` §4.6
- `docs/v2_platform/phases/e58_sqlite_to_postgres_migration.md`
- `docs/v2_platform/phases/e55_plan_step_state_postgres.md` (E55-S3)
- `docs/v2_platform/postgres_production_completeness.md`
- `backend/cli_plugins/database.py`; `backend/persistence/sqlite_to_postgres/`
  (implementation)
- `docs/v2_platform/runbooks/e58_sqlite_to_postgres_cutover.md` (cutover
  runbook, E58-S4-T2)
