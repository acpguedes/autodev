# E8 Restore Runbook — State Store and Artifact Store (E8-S4-T2)

Operational procedure to restore the AutoDev platform from a backup directory
produced by `python -m backend.persistence.backup backup --out <dir>`
(`backend/persistence/backup.py`, `BackupManager`).

Scope: SQLite State Store (local-first), PostgreSQL State Store (production),
and the Artifact Store (local filesystem or MinIO). Targets: **RPO <= 5 min**
(backup schedule) and **RTO <= 30 min** (measured restore, see §5).

## 1. Backup layout

Every backup directory is self-describing:

```
<backup-dir>/
  manifest.json            # schema_version, created_at, per-file SHA-256
  state_store.sqlite3      # SQLite online-backup snapshot (when applicable)
  state_store.pgdump       # pg_dump --format=custom (when applicable)
  artifacts/<bucket>/<object_key>   # mirrored artifact payloads
```

`manifest.json` carries `schema_version` (currently `1`) and a SHA-256 digest
plus size for every copied file. **Never restore from a backup that fails
verification** (§3).

## 2. Taking a backup (scheduled)

```bash
source .venv/bin/activate
python -m backend.persistence.backup backup --out /backups/autodev/$(date +%Y%m%dT%H%M%S)
```

- Exit code `!= 0` means the backup FAILED — see §6 (alerting).
- Schedule: every 5 minutes (cron/systemd timer/CI schedule) to satisfy
  RPO <= 5 min. Components that do not apply to the deployment (e.g.
  PostgreSQL on a local-first SQLite install) are reported as `skipped`,
  which is not a failure.

## 3. Pre-restore integrity checklist

Run all of these before touching production state:

1. `python -m backend.persistence.backup verify --from <backup-dir>`
   must print `manifest OK` and exit `0` (validates `schema_version` and the
   SHA-256 of every file in the manifest).
2. Confirm `created_at` in `manifest.json` is within the acceptable RPO
   window for the incident.
3. Confirm the component set in `manifest.json` matches the deployment
   (`sqlite` **or** `postgres` completed; `artifacts` completed when an
   artifact store is in use).
4. Stop the backend control plane (no writers during restore).

## 4. Restore by component

All components at once:

```bash
source .venv/bin/activate
python -m backend.persistence.backup restore --from <backup-dir>
```

The command verifies the manifest first and exits `!= 0` on any failure.

### 4.1 SQLite State Store

- Restored via the SQLite online-backup API into the path derived from
  `DATABASE_URL` (`sqlite:///...`).
- Manual fallback: copy `state_store.sqlite3` over the database file while
  the backend is stopped, then compare `sha256sum` with the manifest.

### 4.2 PostgreSQL State Store

- Restored via `pg_restore --clean --if-exists --no-owner
  --dbname=$DATABASE_URL state_store.pgdump`.
- Requires `pg_restore` on `PATH` and a reachable database; the CLI skips
  the component when the dump is absent, and fails when `pg_restore` fails.

### 4.3 Artifact Store

- Every mirrored payload is re-uploaded through the **public artifact-store
  API** (`put_artifact`), so bucket layout, tenancy prefixes, and digests are
  re-validated on write; a digest mismatch aborts the restore.
- Works identically for the local filesystem backend and MinIO
  (`STORAGE_BACKEND=s3`).

## 5. Post-restore verification and RTO check

1. Start the backend and run the smoke checks:
   - sessions/runs/messages visible for a known tenant;
   - a known artifact downloads and its SHA-256 matches the manifest entry.
2. Run the automated round-trip test against the restored environment:
   `pytest backend/tests/test_backup_restore.py -q`.
3. **RTO verification:** record wall-clock time from "incident declared" to
   "post-restore checks green". The drill MUST complete in <= 30 min.
   Record the measured time in the incident/drill log. If the drill exceeds
   30 min, open a corrective task against E8-S4.

## 6. Backup-failure alerting

- The CLI exits non-zero on any failure; the scheduler MUST alert on
  non-zero exit (e.g. cron wrapper piping to the alerting channel, or the CI
  schedule marking the run red and notifying the on-call channel).
- Treat a missed schedule tick the same as a failure (RPO breach risk).

## 7. Periodic restore drill (E8-S4-T3)

`backend/tests/test_backup_restore.py` implements seed → backup → wipe →
restore → integrity asserts, with PostgreSQL and MinIO variants that skip
automatically when those services are unavailable. Run it on every CI run
and, additionally, as a scheduled (at least weekly) job against
staging-equivalent PostgreSQL + MinIO to keep the restore path proven.

## Known deviations (DoR)

The E8-S4 DoR asked for E8-S1..S3 ready plus a staging environment; E8-S3
was still partial and no staging or E11 alerting stack existed when this
runbook was written. See the "DoR deviations" subsection of
`docs/v2_platform/phases/e8_persistence_data.md` § E8-S4.
