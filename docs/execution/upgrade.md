# Upgrade & Version Compatibility (E34-S3)

> Story definition: `docs/v2_platform/phases/e34_packaging_global_install.md#e34-s3`.

## `autodev upgrade`

`autodev upgrade [--backup-dir DIR] [--target-version X]`
(`backend/ops/upgrade.py`) runs two steps, always in this order:

1. **Back up** the configured state store and artifact store via the
   existing E8-S4 `BackupManager` contract (`backend/persistence/backup.py`)
   — the same tooling `docs/v2_platform/runbooks/e8_restore_runbook.md`
   documents for disaster recovery. `--backup-dir` defaults to
   `.autodev/upgrade-backups/<UTC timestamp>`.
2. **Migrate**, by constructing the configured store (SQLite or
   PostgreSQL), which applies any pending schema migrations as it always
   does at connect time.

Prints `{"status", "detail", "backup_dir", "release_notes"}` as JSON.

## Compatibility check (E34-S3-T1)

`MigrationRunner.run_pending()` (`backend/persistence/migrations/runner.py`)
now refuses outright — raising `SchemaVersionMismatchError`, caught by
`run_upgrade` and reported as `"status": "refused"` — when a namespace's
recorded schema version is **newer** than the last migration the running
code knows about. This is the "code was downgraded but the database
wasn't" scenario: silently continuing would either be a no-op that masks
the mismatch, or (with a naive implementation) skip migrations the newer
schema actually needs. The backup from step 1 has already run by the time
this check fires, so a refused upgrade still leaves you with a fresh
backup to restore from or to hand to a newer install.

This check lives in the shared `MigrationRunner`, so it protects every
caller — SQLite, PostgreSQL, server startup, and the CLI — not just the
`upgrade` command.

## Rollback posture (E34-S3-T2)

No bespoke rollback mechanism was built. Rollback is **restore from the
pre-upgrade backup** `upgrade` already took, using the existing E8-S4
tooling:

```bash
python -m backend.persistence.backup verify --from <backup_dir>
python -m backend.persistence.backup restore --from <backup_dir>
```

See `docs/v2_platform/runbooks/e8_restore_runbook.md` for the full
restore procedure and RPO/RTO targets. `MigrationRunner.rollback_to()` /
`run_down()` (schema-only, DDL-level rollback) remain available for a
targeted schema rollback within a single store, but a full data-safe
downgrade is the documented restore path, not a schema-only one — a
migration's `down` step is frequently a no-op by design (see
`runner.py::_noop_down`) and was never meant to reconstruct dropped data.

## Release notes hook (E34-S3-T3)

`--target-version X` looks up the `## [X] ...` (or `## X ...`) heading in
`CHANGELOG.md` and includes that section verbatim as `release_notes` in the
JSON output — a best-effort surface, empty string when the version isn't
found. This is deliberately minimal groundwork for the GA v1→v2 upgrade
requirement (E13), not a full release-notes system: no changelog parsing
beyond "find the heading, take everything until the next one."

## Scope reduction (stated, not hidden)

- No automated staging rehearsal or scheduled upgrade job — `autodev
  upgrade` is an operator-invoked command, matching every other `autodev`
  subcommand's posture.
- No downgrade-in-place (migrating a newer schema back down while keeping
  data) — the documented path for that is restore-from-backup onto a
  matching-version install, not a live schema downgrade.
