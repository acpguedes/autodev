# E11 Incident Response Runbook

Executable incident-response procedure for the E11 observability, security,
and multi-tenant surfaces: backup health, sandbox containment, and plugin
containment. Every alert configured in
`infrastructure/observability/prometheus-rules.yml` links to a section of
this document via its `runbook_url` annotation.

## 1. Alert-to-severity and owner table

| Alert | Severity | Owner | First response |
| --- | --- | --- | --- |
| `AutoDevBackupNeverSucceeded` | critical | Platform on-call | §3.1 |
| `AutoDevBackupStale` | critical | Platform on-call | §3.2 |
| `AutoDevBackupFailing` | warning | Platform on-call | §3.3 |
| Suspected sandbox escape / unexpected command execution | critical | Security on-call | §4 |
| Suspected malicious or misbehaving plugin | critical | Security on-call | §5 |

## 2. First five minutes (any alert)

Run these in order before doing anything else — they establish whether the
platform is actually degraded, and give you the raw material for §6
(evidence preservation) without waiting for a second incident to start
collecting it:

1. `curl -s http://<backend-host>:8000/health` — is the API serving at all?
2. Prometheus target health:
   `curl -s http://<prometheus-host>:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health}'`
3. Raw metrics snapshot: `curl -s http://<backend-host>:8000/metrics | head -100`
   (or the OTel Collector's Prometheus exporter at `otel-collector:9464`).
4. Compose service status: `docker compose -f infrastructure/docker-compose.yml ps`
   (add `--profile observability` if the observability stack is also
   suspect).
5. Sanitized logs: `docker compose -f infrastructure/docker-compose.yml logs --tail=200 backend`.
   Every log line already passes through `TelemetryRedactionFilter`
   (`docs/ops/observability.md`); do not paste raw environment variables or
   `.env` contents into a ticket to "add context" — that reintroduces the
   secret the filter just removed.

## 3. Backup alert procedures

All three alerts share one root fact: `docs/v2_platform/runbooks/e8_restore_runbook.md`
is the authoritative backup/restore procedure. This section is only the
triage step that gets you there.

### Backup never succeeded

`AutoDevBackupNeverSucceeded` — `absent(autodev_backup_last_success_timestamp_seconds)`
fired for 5 minutes: the platform has **no evidence a backup has ever
completed**.

1. Check whether backups are actually scheduled at all (cron/systemd
   timer/CI schedule per `e8_restore_runbook.md` §2) — a missing schedule,
   not a failing one, is the most common cause.
2. If scheduled, run one manually and read its exit code and stderr:
   `python -m backend.persistence.backup backup --out /tmp/incident-backup`.
3. Read `AUTODEV_BACKUP_STATUS_PATH` (default `.autodev/backup-status.json`)
   directly — it is sanitized (timestamps, a failure count, a result label
   only) and safe to paste into a ticket verbatim.
4. Common causes: `pg_dump` missing from the container image (fails closed
   as of E11-S4 — see `e8_restore_runbook.md` §2), unreachable database,
   unwritable backup target directory.

### Backup stale

`AutoDevBackupStale` — `time() - autodev_backup_last_success_timestamp_seconds > 300`
fired for 1 minute: the last successful backup is older than the 5-minute
RPO. There *is* history here, unlike the alert above.

1. Confirm the current wall-clock RPO exposure:
   `curl -s 'http://<prometheus-host>:9090/api/v1/query?query=time()-autodev_backup_last_success_timestamp_seconds'`.
2. Check `autodev_backup_consecutive_failures` for the same window — a
   nonzero value means attempts are running but failing (go to §3.3); a zero
   value with a stale timestamp means the scheduler itself stopped firing.
3. Restart the scheduler/cron/timer and confirm the next tick both runs and
   updates the status file.

### Backup failing

`AutoDevBackupFailing` — `autodev_backup_consecutive_failures > 0` fired for
1 minute: at least one recent attempt failed. This is `warning`, not
`critical`, because a single failure inside a 5-minute RPO window is not yet
an RPO breach — but do not wait for it to become one.

1. Read the sanitized status file's `consecutive_failures` and
   `last_attempt_timestamp` to see whether this is a one-off or a pattern.
2. Reproduce with a manual run to get the real stderr (the status file
   deliberately never stores exception text):
   `python -m backend.persistence.backup backup --out /tmp/incident-backup`.
3. Common causes: disk full at the backup target, expired/rotated database
   credentials, `pg_dump`/`pg_restore` version mismatch against the server.

## 4. Sandbox containment

If a validation job is suspected of escaping its container, attempting
network access it shouldn't have, or otherwise behaving outside the
hardened-sandbox contract (`docs/ops/observability.md`,
`backend/validation/sandbox.py`):

1. Immediately set `AUTODEV_ENABLE_SANDBOX=0` (or remove the flag) in the
   backend's environment and restart it:
   `docker compose -f infrastructure/docker-compose.yml restart backend`.
   With the sandbox disabled, every validation job returns a `disabled`/
   `skipped` result instead of spawning a process — this stops new sandboxed
   execution immediately, it does not require waiting for in-flight jobs.
2. Identify and preserve any still-running sandbox container:
   `docker ps --filter ancestor=python:3.11-slim`, then `docker inspect
   <container>` before removing it (see §6).
3. Do not attempt to "clean up" by force-killing containers before capturing
   evidence — a killed container's logs may still be readable via `docker
   logs <container>` even after it exits, but its filesystem state is gone
   once removed.
4. Confirm containment: `backend/tests/integration/test_sandbox_security_contract.py`
   documents the expected hardened behavior (no network, guarded workspace
   only, non-root, no privilege escalation) — re-run it against the restarted
   backend's Docker daemon as a sanity check, not as a substitute for manual
   review of what actually happened.

## 5. Plugin containment

If a plugin is suspected of misbehaving (unexpected resource use, permission
denial spikes in `plugin.permission.denied` events, or a report of malicious
behavior):

1. Disable it immediately through the Control Plane API — this is the same
   action the Extensions screen's disable button takes:
   `curl -X POST http://<backend-host>:8000/v2/extensions/plugin/<plugin_id>/disable`.
   Disabling unloads the plugin's registered extensions and host API access;
   it does not require a backend restart.
2. Confirm the plugin transitioned to `disabled`, not still `enabled`:
   `curl http://<backend-host>:8000/v2/plugins/active` should no longer list
   it.
3. For an `in-process` plugin in production, also check whether it was
   supposed to be running at all: `AUTODEV_TRUSTED_IN_PROCESS_PLUGINS`
   (ADR-020, `docs/v2_platform/decisions/ADR-020-trusted-in-process-plugin-boundary.md`)
   is the operator allowlist — an untrusted or privileged `in-process`
   plugin should never have installed in production in the first place, so
   if one is running, treat the *install* path as compromised, not just this
   one plugin.
4. Preserve the plugin's manifest and lifecycle event history
   (`PluginHost.events`) before considering re-enabling it.

## 6. Evidence preservation

- Copy `AUTODEV_BACKUP_STATUS_PATH`, sanitized logs (`docker compose logs`),
  Prometheus alert history (`/api/v1/alerts`), and `docker inspect` output
  for any implicated container into the incident record.
- **Never** copy raw `.env` files, `docker inspect` `Env` blocks without
  redaction, or process argv containing credentials — `_postgres_cli_connection`
  (`backend/persistence/backup.py`) and `TelemetryRedactionFilter`
  (`backend/observability/log_correlation.py`) exist specifically so this
  data never needs to appear in evidence; do not defeat that by pasting raw
  environment dumps.
- If a secret is suspected to have leaked despite these controls, rotate it
  immediately and record the rotation in the incident log — evidence
  preservation never blocks credential rotation.

## 7. Restore invocation and integrity verification

Follow `docs/v2_platform/runbooks/e8_restore_runbook.md` in full, starting at
its §3 pre-restore integrity checklist. Do not skip the `verify` step even
under time pressure — restoring from an unverified backup can turn a
5-minute RPO breach into a permanent data loss incident.

## 8. Recovery criteria, communication, and incident closure

- **Recovery criteria:** the triggering alert has resolved in Prometheus
  (`/api/v1/alerts`, state `inactive`) for at least one full evaluation
  interval, and the §5 post-restore checks in `e8_restore_runbook.md` (when
  a restore was performed) are green.
- **Communication:** post an initial notice within 15 minutes of
  acknowledgment (even "still investigating"), and a resolution notice with
  root cause and the measured RTO/RPO impact once recovery criteria are met.
- **Closure:** record start time, detection method (alert name or manual
  report), root cause, remediation, measured RTO (if a restore occurred),
  and any follow-up corrective task, in the incident log.

## 9. Quarterly drills

- **Network-denial drill:** run
  `backend/tests/integration/test_sandbox_security_contract.py` against a
  fresh Docker daemon (not a warmed/cached one) and confirm all three tests
  pass with zero skips, matching the CI gate in `.github/workflows/ci-backend.yml`.
- **Restore drill:** follow `e8_restore_runbook.md` §7 end to end against a
  staging-equivalent PostgreSQL + MinIO environment, and record the measured
  RTO. Both drills are quarterly at minimum; run them sooner after any
  change to the sandbox, plugin, or backup code paths.

## 10. Escalation

Escalate beyond the on-call owner immediately, not after further
investigation, when either:

- the 5-minute RPO has been breached (`AutoDevBackupStale` has been firing
  longer than 5 additional minutes past its own `for: 1m`, i.e. the backup
  is now more than ~6 minutes old with no sign of recovery), or
- the 30-minute RTO in `e8_restore_runbook.md` §5 is at risk of being missed
  during an active restore.

Escalation means paging the next on-call tier and opening a dedicated
incident channel — it does not mean waiting for the current owner to decide
they are stuck.
