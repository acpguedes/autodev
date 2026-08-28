# Backup and Restore Runbook

E0 establishes PostgreSQL as the production state store while preserving SQLite
for local-first development.

## Targets

- RPO: <= 5 minutes.
- RTO: <= 30 minutes.

**RPO mechanism (ADR-027).** RPO is met by a five-minute `BackupManager`
cron of complete logical snapshots (`pg_dump`/SQLite online backup) — not
continuous WAL archiving/PITR, which reference §13.9 describes as the
target architecture but which this deployment topology's Beta scope
deliberately defers (no staging environment to drill it, no existing
restore path that replays WAL). See ADR-027 for the full rationale and the
condition that would reopen it.

The real worst-case RPO is **the schedule interval plus the backup's own
duration**, not the interval alone — a backup that overruns its slot
silently widens the data-loss window. Every attempt records its duration at
`AUTODEV_BACKUP_STATUS_PATH` and exposes it as
`autodev_backup_last_duration_seconds` (E59-S3-T2); monitor it and treat a
duration regularly exceeding ~20% of the schedule interval as the signal to
shorten the interval or revisit ADR-027, not a number to ignore.

## Local PostgreSQL Stack

Start the local PostgreSQL service when validating production-profile storage:

```bash
docker compose -f infrastructure/docker-compose.yml --profile postgres up -d postgres
```

The URL takes the form `postgresql://<user>:<password>@<host>:5432/autodev`
(`postgres` as `<host>` from containers on the Compose network, `localhost`
from the host). Set `AUTODEV_POSTGRES_PASSWORD` (`.env.example`) to a real,
non-default credential — production rejects an empty or known-default
PostgreSQL password (`autodev`, `password`, `changeme`, `change-me`; E11-S4).
There is deliberately no sample password in this document or in
`infrastructure/docker-compose.yml`.

## Backup

Use the platform's own `BackupManager` CLI, not raw `pg_dump`, so SQLite,
PostgreSQL, and the artifact store are captured together under one
self-describing, digest-verified manifest:

```bash
source .venv/bin/activate
python -m backend.persistence.backup backup --out /backups/autodev/$(date +%Y%m%dT%H%M%S)
```

- **Schedule this every 5 minutes** (cron/systemd timer/CI schedule) to meet
  the RPO target above.
- A component that does not apply to the deployment (e.g. PostgreSQL on a
  local-first SQLite install) is reported `skipped`. A component that *is*
  configured but whose CLI tool (`pg_dump`) is missing fails the whole
  backup closed instead — see `docs/v2_platform/runbooks/e8_restore_runbook.md`.
- **RLS-scoped tables need a maintenance connection (E57-S4).** The app's own
  `DATABASE_URL` role deliberately cannot bypass Row-Level Security
  (E56-S3-T2), so a whole-database `pg_dump`/`pg_restore` against a
  PostgreSQL deployment needs `AUTODEV_BACKUP_DATABASE_URL` set to a
  separate superuser/`BYPASSRLS` connection on the same database — see
  `docs/v2_platform/runbooks/e8_restore_runbook.md` §4.2.
- Every attempt, success or failure, is durably recorded at
  `AUTODEV_BACKUP_STATUS_PATH` (default `.autodev/backup-status.json`,
  owner-only `0600`, sanitized — no exception text or secret material) and
  exposed as Prometheus gauges
  (`autodev_backup_last_attempt_timestamp_seconds`,
  `autodev_backup_last_success_timestamp_seconds`,
  `autodev_backup_consecutive_failures`, `autodev_backup_last_result`,
  `autodev_backup_last_duration_seconds`)
  through the E11-S1 OpenTelemetry meter — see `docs/ops/observability.md`.
- **PostgreSQL coverage is asserted, not assumed (E59-S1).** After
  `pg_dump` runs, `BackupManager` enumerates every live `public`-schema
  table and diffs it against the dump's own table of contents
  (`pg_restore --list`); a live table the dump did not capture fails the
  backup closed instead of shipping a manifest that silently omits data.
  The manifest also records the pgvector extension's version and its
  vector indexes, so a restore target missing the extension is rejected
  before `pg_restore` runs, not mid-restore.
- `AutoDevBackupNeverSucceeded`, `AutoDevBackupStale`, and
  `AutoDevBackupFailing` alert on this signal
  (`infrastructure/observability/prometheus-rules.yml`); each links to
  `docs/v2_platform/runbooks/e11_incident_response.md` for the response
  procedure.

Store backup artifacts outside the database host and verify retention policies
match the deployment's compliance requirements.

**Coverage note (E55, E59-S1).** The SQLite/PostgreSQL components above are
whole-database snapshots, so every domain store sharing `DATABASE_URL` is
captured — including
`plan_step_state` (per-step plan approval state,
`backend/plans/step_state.py` `StepApprovalStore`) now that it lives in that
same physical database rather than a standalone SQLite file this tooling
never saw. A pre-E55 install's leftover `./autodev_plan_step_state.db` (if
one exists) is outside `DATABASE_URL` and therefore outside this backup
entirely; migrate it once with
`python -m backend.persistence.step_state_migration` before relying on
`BackupManager` as its only durability guarantee — the legacy file is never
deleted by that migration, so it remains a fallback source even after.

## Restore

Use the same CLI — it verifies the manifest before touching anything:

```bash
source .venv/bin/activate
python -m backend.persistence.backup verify --from <backup-dir>
python -m backend.persistence.backup restore --from <backup-dir>
```

After restore, run the backend health check and a session/run listing smoke test.

## Full procedure and drills

This page covers the local-development quick reference only. The full,
executable restore procedure — pre-restore integrity checklist, per-component
restore steps, RTO measurement, backup-failure alerting, and the quarterly
restore drill — is `docs/v2_platform/runbooks/e8_restore_runbook.md`.

## Clean-environment restore drill (E59-S2)

`.github/workflows/ci-e2e.yml`'s `prod-e2e` job runs the full drill against
real PostgreSQL + MinIO on every pull request **and** on a daily schedule
(`workflow_dispatch` also available on demand) — not merely on code changes:
backup, wipe (drop + recreate the database; replace the MinIO container
outright, not just empty it), restore into that genuinely clean environment,
and prove the restored environment actually serves data across all four
surfaces this program depends on: session listing, secret resolution
(metadata **and** decrypted plaintext), artifact resolution (byte-for-byte),
and a rerun vector query through the restored HNSW index. Measured RTO is
recorded to the job summary and uploaded as a build artifact
(`backup-drill-rto`).

A local drill run against `pgvector/pgvector:0.8.3-pg16` plus fresh
Redis/MinIO containers measured: backup ≈ 1.5 s for a minimal seeded
dataset, and a full clean-environment restore with all four functional
checks passing in ≈ 10.9 s — both far inside the ≤ 30 min RTO target.
Production numbers scale with data volume; trust the CI job's own recorded
number for the deployment's real dataset size, not this illustrative local
figure.
