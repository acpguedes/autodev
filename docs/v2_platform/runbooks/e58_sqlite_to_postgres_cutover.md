# SQLite to PostgreSQL Cutover Runbook (E58)

Companion to `docs/v2_platform/decisions/ADR-026-sqlite-to-postgres-migration.md`
(the design decisions this runbook follows) and
`docs/v2_platform/phases/e58_sqlite_to_postgres_migration.md` (the epic).
Use this when promoting an existing SQLite installation to PostgreSQL.

## 1. Prerequisites

- A reachable PostgreSQL database at the schema version this install's code
  produces. `autodev database migrate` refuses to proceed against a
  mismatched schema (`docs/execution/cli-install.md` — run `autodev upgrade`
  against the SQLite source first if it is behind).
- The destination database is either empty, or you have confirmed it is safe
  to write into anyway (`--confirm-nonempty-destination`).
- `pgvector` installed on the destination if repository indexing
  (`code_chunks`) is in use — preflight reports this, it does not install it.
- A maintenance window. Cutover is not zero-downtime (ADR-026 decision 11):
  dual-write is prohibited, so there is a window between "source stops
  accepting writes" and "destination accepts traffic" during which the
  platform is unavailable.

## 2. Rehearse with a dry run

Before the maintenance window, rehearse against a copy of the source (or the
source itself — `--dry-run` writes nothing to either database):

```bash
autodev database migrate --from sqlite:///path/to/autodev.db \
  --to postgresql://user:pass@host:5432/autodev --dry-run
```

Review the printed plan: preflight errors/warnings, per-table row counts, and
whether the legacy standalone `autodev_plan_step_state.db` file was detected.
Resolve every preflight error before the maintenance window — a dry run
surfaces the same schema-version and table-inventory checks the real run
enforces, without the time pressure of a live window.

## 3. Maintenance window — order of operations

1. **Stop write traffic to the source.** Take the application offline, or
   point it at a maintenance page. The migrator reads a consistent snapshot
   (a `BEGIN DEFERRED` transaction held for the whole copy), but new writes
   after that snapshot is taken would silently not be migrated — the source
   must genuinely be read-only for the duration of step 3.2.
2. **Run the migration:**

   ```bash
   autodev database migrate --from sqlite:///path/to/autodev.db \
     --to postgresql://user:pass@host:5432/autodev \
     --report /var/log/autodev/e58-migration-$(date +%Y%m%d%H%M%S).json
   ```

   This applies the destination schema, copies every table in dependency
   order, adjusts sequences, migrates the standalone step-state file (if
   present), verifies artifact pointers, and reconciles — persisting the
   full result to `--report`. Keep that file; it is the evidence a cutover
   decision is based on (ADR-026 decision 9) and is safe to attach to a
   change record (connection strings are redacted, never included).
3. **Check the result before doing anything else.** The command exits
   non-zero if preflight refused or reconciliation did not pass cleanly. Do
   not proceed to step 4 on a non-zero exit — see §5.
4. **Verify the destination**, independent of the migrator's own
   reconciliation:
   - `autodev doctor` against `DATABASE_URL` pointed at the destination.
   - Spot-check a handful of sessions/runs/secrets against the source by
     hand (a secret's ciphertext must decrypt exactly as it did on the
     source — the migrator never re-encrypts, so a decryption failure here
     means the ciphertext transcription itself is suspect, not the key).
5. **Point `DATABASE_URL` at the destination** and restart the application.
6. **Only now does the destination accept traffic.** There is no dual-write
   period before this point and none is introduced after it (ADR-026
   decision 11) — the source was read-only from step 3.1 onward and stays
   that way; it is not deleted, only retired.

## 4. Rollback

The source was never mutated (ADR-026 decision 2) and the legacy step-state
file was never deleted (ADR-026 decision 3, unchanged from E55-S3's own
rollback posture). Rollback is:

1. Point `DATABASE_URL` back at the SQLite source.
2. Restart the application.

There is no reverse (PostgreSQL -> SQLite) migration path and none is
planned — rollback means returning to the untouched source, not migrating
backward. If the destination was already receiving traffic before the
rollback decision, any writes it accepted are lost on rollback (the same
trade-off every one-way cutover carries) — this is why §3 step 4's
verification happens *before* step 5 repoints traffic.

## 5. If the migration itself fails

Refer to the `--report` JSON's `preflight` and `reconciliation` sections —
they name exactly which check failed or which table did not reconcile.

- **Preflight refused**: nothing was written to the destination. Fix the
  reported problem (schema version, unknown table, missing extension) and
  re-run from §3 step 2 — the source is untouched, so there is nothing to
  undo.
- **Reconciliation did not pass**: the destination now has *some* data
  (safe: every insert is `ON CONFLICT DO NOTHING`, so nothing was
  duplicated), but do not cut traffic over to it. Per ADR-026's rollback
  plan, discard the destination database and recreate it rather than
  repairing it by hand — the source remains authoritative until a clean
  report exists. Investigate the specific mismatched table before
  re-running; a content-hash mismatch (not just a count mismatch) usually
  means the destination was written to by something other than this
  migrator between runs.
- **Interrupted mid-run** (process killed, connection dropped): re-run the
  exact same command. Every table copy commits independently and is
  `ON CONFLICT DO NOTHING`, so a resumed run only re-attempts work, never
  duplicates it (E58-S4-T1). Preflight will report the destination as
  non-empty on the resumed run — pass `--confirm-nonempty-destination`, the
  same as any other resumption.

## 6. Follow-up

- Retire the source SQLite file per your organization's data-retention
  policy once the destination has run in production long enough to be
  confident — this runbook does not prescribe a retention window.
- If artifact pointers were reported dangling in the migration report,
  investigate before relying on those specific artifacts; the row migrated
  correctly, only the referenced object could not be found in the currently
  configured object store (moving artifact payloads themselves is out of
  E58's scope, per ADR-026).
