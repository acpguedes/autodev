# E58 — SQLite to PostgreSQL Data Migration

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/4
**Depends on:** E50 (destination schema), E51-E55 (both backends behave
identically), E57 (a real PostgreSQL to migrate into, in CI)
**Enables:** existing local-first installations to be promoted to production
without data loss — the "progressive upgrade without rewriting" the reference
document promises at §4.6 but which no procedure currently implements.
**Canonical source:** this document. `autodev upgrade`
(`backend/ops/upgrade.py:85`) migrates a state store's *schema* forward, but
nothing anywhere moves *data* from SQLite into PostgreSQL, and no
documentation describes doing so.

## Context and problem

The platform's local-first story ends at a cliff. A user can run on SQLite
indefinitely, and the documentation says moving to PostgreSQL is a
configuration change. In practice, changing `DATABASE_URL` from
`sqlite://` to `postgresql://` starts an empty database: sessions, runs,
messages, plans, quotas, secrets, and policies all appear to vanish.

There is no dry run, no preflight, no reconciliation, and no rollback path.
An operator attempting the move today has to write their own migration and
has no way to verify it moved everything.

Two data sources make this harder than a single table copy. Secrets are
stored as ciphertext and must cross unchanged — re-encrypting or
double-encrypting them would render every credential unusable. And plan step
state lives in a *separate* SQLite file outside `DATABASE_URL`
(`./autodev_plan_step_state.db`), invisible to any migration that reads only
the configured source database; E55-S3 handles that file, and this epic must
not silently assume it does not exist.

## Evidence in code

- `backend/ops/upgrade.py:85` — `run_upgrade(backup_dir, target_version)`
  backs up, then constructs the store to trigger
  `MigrationRunner.run_pending()`; `:113-126` handles
  `SchemaVersionMismatchError`. Schema only — no data movement.
- `backend/cli.py:64` — `subparsers` root; `:260-274` the `upgrade` command.
  There is **no `database` namespace and no `migrate` command**, and
  `grep -n "migrat" Makefile` returns nothing.
- `backend/cli_plugins/__init__.py:23-52` — `register_subcommands()`
  auto-discovers every non-underscore module in `backend/cli_plugins/` and
  calls its `register(subparsers)`. Adding
  `backend/cli_plugins/database.py` is the zero-touch extension point.
- `backend/persistence/database.py:26-40` — `get_store()` selects a backend
  from one URL; nothing in the codebase opens a source and a destination
  store simultaneously.
- `backend/secret_store/store.py:91` — `secrets` holds ciphertext.
- `backend/plans/step_state.py:132` — the separate step-state file.
- `backend/artifacts/pointers.py` — artifact rows are pointers into
  MinIO/S3; the payloads themselves are not in either database and must not
  be copied, only re-pointed correctly.

## Objective

Provide a verifiable, resumable, one-way migration from an existing SQLite
installation to PostgreSQL, with a dry run, a reconciliation report, an
explicit cutover policy, and a rollback path — so a promotion can be
rehearsed before it is performed.

## Key result

An existing SQLite installation is promoted to PostgreSQL with no loss, no
duplication, and no semantic change: row counts and content hashes reconcile
per table, secrets still decrypt, and artifact pointers still resolve.

## Scope

- A command in the shape of
  `autodev database migrate --from sqlite:///... --to postgresql://...`.
- Dry run and preflight.
- Applying the destination schema.
- Consistent read of the source.
- Dependency-ordered copy preserving identifiers.
- Sequence adjustment, timestamps, and JSON documents.
- Encrypted secrets carried as ciphertext.
- The standalone `autodev_plan_step_state.db`.
- Artifact rows and pointers.
- Count and hash validation with a reconciliation report.
- Safe resumption and idempotency.
- Cutover policy and rollback.
- An explicit prohibition on permanent dual-write.

## Out of scope

- PostgreSQL → SQLite migration. The path is deliberately one-way; rollback
  is "return to the untouched source", not a reverse migration.
- Live, zero-downtime migration. Cutover assumes a maintenance window, stated
  rather than implied.
- Cross-version migration between differing schema versions — both sides must
  be at the same version, enforced by preflight.
- Moving artifact payloads between object stores.

## Stories

### E58-S1 — Command, preflight and dry run

Subtasks:
- `E58-S1-T1`: add `backend/cli_plugins/database.py` registering a `database`
  namespace with a `migrate` subcommand taking `--from` and `--to`, following
  the existing auto-discovery contract.
- `E58-S1-T2`: preflight — both URLs reachable, destination schema version
  equal to the source's, destination empty or explicitly confirmed, required
  extensions present, and the standalone step-state file detected and
  reported if present.
- `E58-S1-T3`: `--dry-run` reporting exactly what would move — tables, row
  counts, and detected problems — while writing nothing.

| Criterion | Detail |
| --- | --- |
| Functional | `--dry-run` produces a complete migration plan and writes nothing; preflight refuses mismatched schema versions |
| Non-functional | Credentials never printed or logged; the command is discoverable via `autodev database --help` |
| DoR (specific) | E50-E55 merged (destination schema and parity exist) |
| DoD (specific) | Dry run against a populated SQLite install, and preflight rejecting a version mismatch |
| Dependencies | E50, E51-E55 |

### E58-S2 — Ordered copy with identity preservation

Subtasks:
- `E58-S2-T1`: copy tables in dependency order so foreign keys are
  satisfiable, preserving primary keys and all cross-table identifiers.
- `E58-S2-T2`: adjust sequences after the copy so newly generated identifiers
  cannot collide with migrated ones — the classic post-migration defect.
- `E58-S2-T3`: convert timestamps to `TIMESTAMPTZ` and JSON text to `JSONB`
  without changing meaning, and carry secret ciphertext through byte-for-byte
  with no re-encryption.

| Criterion | Detail |
| --- | --- |
| Functional | All tables copied with identifiers preserved; secrets decrypt after migration; sequences cannot collide |
| Non-functional | Reads are consistent — a source snapshot, not a moving target; conversions are lossless |
| DoR (specific) | E58-S1 merged |
| DoD (specific) | A migrated install where every secret decrypts and a newly created row gets a non-colliding id |
| Dependencies | E58-S1 |

### E58-S3 — Auxiliary sources and reconciliation

Subtasks:
- `E58-S3-T1`: migrate the standalone `autodev_plan_step_state.db` when it
  exists, coordinating with E55-S3 so the work is done once and not twice.
- `E58-S3-T2`: migrate artifact rows and pointers, verifying that the
  referenced objects still resolve in the configured object store rather than
  assuming they do; report dangling pointers instead of copying them
  silently.
- `E58-S3-T3`: reconciliation — per-table row counts and content hashes
  compared between source and destination, emitted as a report that is the
  artifact an operator uses to decide whether to cut over.

| Criterion | Detail |
| --- | --- |
| Functional | Step state and artifact pointers migrate; dangling pointers reported, not hidden |
| Non-functional | Reconciliation compares counts *and* hashes; a mismatch fails the migration rather than warning |
| DoR (specific) | E58-S2 merged; E55-S3 merged |
| DoD (specific) | Reconciliation report for a full migration, and a deliberately corrupted row detected |
| Dependencies | E58-S2, E55-S3 |

### E58-S4 — Resumption, cutover and rollback

Subtasks:
- `E58-S4-T1`: safe resumption after an interruption, and idempotency — a
  re-run must not duplicate rows.
- `E58-S4-T2`: document the cutover policy — the maintenance window, the
  order of operations, when the source becomes read-only, and how to verify
  the destination before accepting traffic.
- `E58-S4-T3`: rollback posture (return to the untouched source) and the
  explicit prohibition on permanent dual-write, recorded in ADR-026.

| Criterion | Detail |
| --- | --- |
| Functional | An interrupted migration resumes without duplication; a full re-run is a no-op |
| Non-functional | No dual-write mode exists, even temporarily, beyond the documented cutover window |
| DoR (specific) | E58-S3 merged; ADR-026 drafted |
| DoD (specific) | Interrupt-and-resume test; ADR-026 `Accepted`; runbook published |
| Dependencies | E58-S3 |

## Contracts and decisions

### Architectural decisions required

- **ADR-026 — SQLite to PostgreSQL migration and cutover**
  (`decisions/ADR-026-sqlite-to-postgres-migration.md`, `Proposed`):
  one-way migration, the cutover policy, and the prohibition on permanent
  dual-write. Decided within E58-S4.

Dual-write is prohibited because it needs conflict resolution the platform
has no model for, and because it makes "which database is authoritative"
ambiguous exactly when an operator most needs certainty. A maintenance window
is the honest trade.

### Security and multitenancy

- Secret ciphertext crosses unchanged. Re-encryption during migration would
  put plaintext in the migrator's memory and risk rendering every credential
  unusable; the migrator must never decrypt.
- Connection strings for both databases must not be logged or written into
  the reconciliation report.
- `tenant_id` must be preserved exactly; a migration that defaults tenants
  would silently merge tenants. Rows with no tenant map to
  `DEFAULT_TENANT_ID` explicitly and are counted in the report.
- After migration, RLS applies at the destination; the migrator itself
  necessarily operates across tenants and must therefore run as an operator
  task, never exposed through the API.

### Migration strategy

- Both sides must be at the same schema version, enforced by preflight; the
  destination schema is created by the normal migration runner, not by the
  migrator.
- The copy is ordered by dependency, resumable, and idempotent.
- Reconciliation is a gate, not a warning.

### Compatibility and rollback

- The source database is never mutated. Rollback is pointing
  `DATABASE_URL` back at it.
- The step-state file is likewise retained, not deleted.
- The reconciliation report is the evidence that cutover is safe; without a
  clean report, cutover does not proceed.

## Testing and observability

Tests required:
- Dry run against a populated install, writing nothing.
- Preflight rejecting a schema-version mismatch and a non-empty destination.
- Full migration with per-table count and hash reconciliation.
- Secrets decrypting after migration.
- Sequence adjustment preventing identifier collision.
- Step-state file migrated when present, and correctly skipped when absent.
- Dangling artifact pointers reported.
- Interrupt and resume without duplication; full re-run as a no-op.
- Corrupted-row detection failing the migration.

Observability:
- A progress indicator per table for long migrations.
- The reconciliation report persisted as a file, not only printed, so it can
  be attached to a change record.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Sequences not adjusted after copy | New rows collide with migrated ids, corrupting data after a seemingly successful migration | E58-S2-T2, with an explicit post-migration insert test |
| Secrets re-encrypted or double-encrypted | Every credential becomes unusable | The migrator never decrypts; ciphertext carried byte-for-byte (E58-S2-T3) |
| Step-state file forgotten | Approvals silently lost after promotion | Preflight detects and reports it (E58-S1-T2); E58-S3-T1 migrates it |
| Partial migration accepted as complete | Silent data loss discovered later | Reconciliation is a hard gate (E58-S3-T3) |
| Operator attempts dual-write to avoid downtime | Ambiguous authority, divergent data | Prohibited in ADR-026; cutover policy documents the window instead |
| Tenant defaulting merges tenants | Cross-tenant data exposure | `tenant_id` preserved exactly; defaulted rows counted and reported |

## DoR / DoD

- **DoR:** E50-E55 merged; a real PostgreSQL available; ADR-026 drafted; a
  representative populated SQLite installation available for rehearsal.
- **DoD:** all four story DoDs met; a populated SQLite install migrated with a
  clean reconciliation report; secrets decrypt; resumption proven; ADR-026
  `Accepted`; cutover runbook published; `docs/v2_platform/progress.md`
  updated; no push or PR without explicit authorization.

## Exit evidence

1. Dry-run output for a populated installation.
2. Reconciliation report showing matching counts and hashes for every table.
3. Post-migration proof: a secret decrypting and a newly inserted row
   receiving a non-colliding identifier.
4. Interrupt-and-resume output showing no duplication.
5. ADR-026 at `Accepted` and the cutover runbook.

## Affected documents and code

Documents: `docs/v2_platform/progress.md`,
`decisions/ADR-026-sqlite-to-postgres-migration.md`, `decisions/README.md`,
`docs/config.md` (promotion path), `docs/ops/backup_restore.md`
(pre-migration backup), a new cutover runbook under
`docs/v2_platform/runbooks/`, `docs/execution/cli-install.md`
(`autodev upgrade` vs `autodev database migrate`).

Code: `backend/cli_plugins/database.py` (new), `backend/persistence/`
(migration implementation), `backend/ops/upgrade.py` (relationship to the new
command).
