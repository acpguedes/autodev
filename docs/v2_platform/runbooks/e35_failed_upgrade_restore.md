# Failed Upgrade — Restore Runbook (E35-S3)

Extends `docs/v2_platform/runbooks/e8_restore_runbook.md` (the authoritative
backup/restore procedure) with the specific failure modes `autodev upgrade`
(E34-S3, `backend/ops/upgrade.py`) can hit.

## 1. Identify which failure mode you're in

`autodev upgrade` prints `{"status", "detail", "backup_dir", "release_notes"}`.
The `status` field tells you exactly where it stopped — do not guess:

| `status` | Meaning | What already happened |
| --- | --- | --- |
| `"ok"` | Backup + migration both succeeded | Nothing to restore; not this runbook |
| `"refused"` | `MigrationRunner` raised `SchemaVersionMismatchError` — the database's recorded schema is *newer* than the installed code's migration list | Backup **already completed** before the refusal (`backup_dir` is populated) |
| `"backup_failed"` | The pre-migrate backup itself failed | **No migration was ever attempted** — the database is untouched, exactly as it was before `upgrade` ran |

## 2. `"refused"` — schema newer than installed code

This is the "code was downgraded but the database wasn't" scenario
(`docs/execution/upgrade.md`). Two ways out, in order of preference:

1. **Install the newer code** that matches the database's recorded schema
   version, then re-run `autodev upgrade` — it will find `current <=
   known` and proceed normally. This is the common case: someone rolled
   the *binary* back without rolling the *database* back, usually by
   accident.
2. **Restore the fresh backup** `upgrade` already took
   (`backup_dir` from the JSON output) onto a database that matches the
   currently-installed code's schema version, if going forward with the
   newer code is not an option:

   ```bash
   python -m backend.persistence.backup verify --from <backup_dir>
   python -m backend.persistence.backup restore --from <backup_dir>
   ```

   Note this restores the database to the state it was in *at the moment
   of the refused upgrade attempt* — it does not roll the schema back
   further. If you need to go further back, use an earlier backup per
   `e8_restore_runbook.md`.

Do **not** attempt to force the migration past the refusal (e.g. by hand-
editing the `schema_version` table) — the refusal exists precisely because
the installed code's migration list cannot be trusted to apply correctly
against a schema it doesn't recognize; the code and the schema need to
agree, one way or the other, before anything writes to that database again.

## 3. `"backup_failed"` — nothing was touched

The database is exactly as it was; the "restore" step is only relevant to
figuring out *why the backup failed*, not to recovering data. Check `detail`
in the JSON output — it is the underlying error verbatim (disk full,
`pg_dump` missing, unreachable database, unwritable backup target — the
same causes `e11_incident_response.md` §3.1 lists for backup alerts).
Resolve that cause, then re-run `autodev upgrade`; nothing needs restoring.

## 4. Downgrade posture

There is no live schema-downgrade path (`docs/execution/upgrade.md`
states this explicitly: a migration's `down` step is frequently a no-op by
design). If you need to run an *older* version of AutoDev against data
produced by a newer one, restore the newer version's own backup onto a
host running the newer code — do not attempt to migrate a newer schema
down to satisfy older code.

## 5. Verification after any restore

```bash
autodev doctor
autodev bootstrap
```

`doctor`'s `database` check confirms the store is reachable again;
`bootstrap` re-runs preflight and (re-)applies any pending migration for
the code version now actually running. Cross-check `autodev --version`
against the version the restored backup's data was produced by.

## 6. Follow-up

- If `"refused"` fired in a context where it *shouldn't* have (the schema
  genuinely should be considered compatible), that is a
  `SchemaVersionMismatchError` false positive — file it against
  `backend/persistence/migrations/runner.py`, do not work around it by
  restoring older data over newer data.
- RPO/RTO targets and the full staging-validation gap are tracked in
  `docs/v2_platform/beta_gap_analysis.md` §11, criterion 6 — this runbook
  documents the *procedure*, it does not by itself close that gap (no
  staging environment exists to rehearse against yet).
