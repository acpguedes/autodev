# Backup and Restore Runbook

E0 establishes PostgreSQL as the production state store while preserving SQLite
for local-first development.

## Targets

- RPO: <= 5 minutes.
- RTO: <= 30 minutes.

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
- Every attempt, success or failure, is durably recorded at
  `AUTODEV_BACKUP_STATUS_PATH` (default `.autodev/backup-status.json`,
  owner-only `0600`, sanitized — no exception text or secret material) and
  exposed as Prometheus gauges
  (`autodev_backup_last_attempt_timestamp_seconds`,
  `autodev_backup_last_success_timestamp_seconds`,
  `autodev_backup_consecutive_failures`, `autodev_backup_last_result`)
  through the E11-S1 OpenTelemetry meter — see `docs/ops/observability.md`.
- `AutoDevBackupNeverSucceeded`, `AutoDevBackupStale`, and
  `AutoDevBackupFailing` alert on this signal
  (`infrastructure/observability/prometheus-rules.yml`); each links to
  `docs/v2_platform/runbooks/e11_incident_response.md` for the response
  procedure.

Store backup artifacts outside the database host and verify retention policies
match the deployment's compliance requirements.

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
