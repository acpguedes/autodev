# ADR-027: RPO via Periodic Base Backups, Not Continuous WAL Archiving

- **Status:** Accepted
- **Date:** 2026-08-27
- **Authors:** AutoDev platform team
- **Related epic:** E59
- **Supersedes/Relates to:** ADR-025 (SQL persistence boundary), ADR-026
  (SQLite to PostgreSQL migration); supersedes reference §13.9's PITR
  expectation for the v2.0-beta deployment topology only

## Context

Reference §13.9 specifies the RPO ≤ 5 min target be met by "periodic base
backups + continuous WAL archiving (PITR)", with a standby replica to speed
up RTO. `docs/ops/backup_restore.md` and
`docs/v2_platform/runbooks/e8_restore_runbook.md` have instead documented a
five-minute `python -m backend.persistence.backup backup` cron since E8-S4,
without ever recording that this is a deliberate departure from §13.9 rather
than an oversight. E59 was scoped in part to resolve this silently
disagreeing pair explicitly (E59-S3-T1).

Continuous WAL archiving requires: a WAL archive destination (object storage
or a dedicated archive host) wired into `archive_command`; a base-backup tool
(`pg_basebackup` or an equivalent) taken on its own schedule, separate from
`BackupManager`'s logical `pg_dump`; and a restore procedure that replays WAL
segments to a target LSN or timestamp, which `BackupManager.restore` does not
implement (`backend/persistence/backup.py`'s PostgreSQL restore is
`pg_restore` against one logical dump — a full-database snapshot, not
point-in-time). A standby replica is explicitly out of scope for this epic
(deployment topology, deferred past Beta by the phase doc itself).

v2.0-beta's actual deployment topology (`docs/v2_platform/beta_gap_analysis.md`
§11 criterion 6) has no persistent staging environment and no operated
PostgreSQL fleet beyond a single instance per deployment
(`infrastructure/docker-compose.yml`'s `postgres` service, or an operator's
managed PostgreSQL). Building WAL archiving and PITR restore now would add a
new archive-storage dependency, a new restore code path
(`BackupManager` has none today), and new failure modes — with no environment
in this program's scope to operate or drill it against.

## Decision

**RPO ≤ 5 min for v2.0-beta is met by a five-minute `BackupManager` cron
(logical `pg_dump` snapshots), not continuous WAL archiving.** This is a
deliberate deviation from reference §13.9's PITR mechanism, scoped to the
Beta deployment topology, not a correction of §13.9 itself.

1. **Mechanism.** `python -m backend.persistence.backup backup` runs every 5
   minutes (`docs/ops/backup_restore.md`, `e8_restore_runbook.md` §2). Each
   run produces one complete, self-describing, digest-verified snapshot
   (SQLite or PostgreSQL, plus artifacts) — no partial/incremental state, no
   WAL replay on restore.
2. **RPO is the schedule interval plus the backup's own duration**, not the
   schedule interval alone: a backup that overruns its 5-minute slot pushes
   the real worst-case data-loss window past the target without any code
   change failing loudly. `BackupManager`'s CLI now times every attempt and
   records it durably (`autodev_backup_last_duration_seconds`,
   `backend/persistence/backup_status.py`, E59-S3-T2) precisely so this is a
   measured number, not an assumption — see the runbook's RPO section for
   the worst-case formula and the alerting threshold.
3. **The trigger to revisit this decision**: data volume growing enough that
   `autodev_backup_last_duration_seconds` regularly exceeds roughly 20% of
   the schedule interval (i.e., a backup taking over ~1 minute on a 5-minute
   schedule), or a deployment acquiring a staging environment capable of
   drilling PITR restore end to end. Either condition should reopen this ADR
   rather than silently shortening the cron interval indefinitely.
4. **Nothing here touches SQLite.** The online-backup snapshot for
   local-first installs is unaffected; this decision concerns only the
   PostgreSQL production topology reference §13.9 describes.

## Alternatives considered

- **Implement PITR now** (continuous WAL archiving + `pg_basebackup` +
  LSN/timestamp-targeted restore). Rejected for this epic: no staging
  environment exists to drill it (the same gap E59-S2 was scoped to close
  for the existing snapshot-restore path), it requires a new archive-storage
  dependency and a new restore code path with no existing test coverage, and
  the phase doc explicitly frames the choice between "implement as
  specified" and "record a deliberate deviation" as this story's decision to
  make, not something to defer further.
- **Shorten the cron interval instead of measuring duration** (e.g. drop to
  1 minute unconditionally). Rejected: makes the RPO number *look* tighter
  without proving it — an unmeasured, overrunning backup at a 1-minute
  interval is no more trustworthy than one at 5 minutes. Measuring duration
  (Decision #2) is a prerequisite for any interval choice being meaningful.
- **A standby replica for faster RTO.** Reference §13.9 pairs this with
  PITR. Out of scope here regardless of the PITR decision — it is a
  deployment-topology change the phase doc places beyond Beta.

## Consequences

- **RPO is honestly bounded by measurement, not assumed from the schedule
  alone.** Operators can see `autodev_backup_last_duration_seconds` (E59-S3)
  and know their actual worst-case data-loss window, not just the configured
  interval.
- **No sub-5-minute RPO is available in v2.0-beta.** A deployment with an
  RPO requirement tighter than ~5 minutes needs PITR, which this ADR
  explicitly defers rather than provides.
- **Restore remains one operation, one code path** (`BackupManager.restore`)
  regardless of how far back the incident is — there is no "restore to this
  exact second" capability, only "restore to the most recent (or a chosen
  historical) complete snapshot". This keeps the E59-S2 clean-environment
  restore drill's scope stable: it drills exactly the mechanism operators
  will actually use.
- **The architecture reference and the operational runbooks now agree
  explicitly**, closing the divergence E59 was scoped to resolve — reference
  §13.9 continues to describe the target architecture and is not edited by
  this ADR; the runbooks now cite this ADR as their deviation's source of
  authority.

## Rollback plan

Reverting this decision means implementing PITR as reference §13.9
specifies: WAL archiving, `pg_basebackup`, and a new
`BackupManager`/CLI restore path accepting a target LSN or timestamp, plus a
staging environment to drill it. Nothing in this ADR blocks that work; the
duration-measurement mechanism (Decision #2) continues to be useful
independent of which RPO mechanism is chosen.

## References

- `docs/architecture/v2_platform_reference.md` §13.9.
- `docs/ops/backup_restore.md`, `docs/v2_platform/runbooks/e8_restore_runbook.md`.
- `docs/v2_platform/phases/e59_backup_restore_disaster_recovery.md` (E59-S3).
- `backend/persistence/backup.py`, `backend/persistence/backup_status.py`,
  `backend/observability/backup_metrics.py`.
