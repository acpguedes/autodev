# E59 — Backup, Restore and Disaster Recovery

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/3
**Depends on:** E8-S4 (`BackupManager`, manifest, RPO/RTO targets), E55-S3
(step state inside the state store), E58 (PostgreSQL as the live source),
E57-S4 (automated restore in CI)
**Enables:** closing open Beta criterion 6 — "backup/restore validated (RPO
≤ 5 min, RTO ≤ 30 min)" — which `beta_gap_analysis.md` §11 records as **Open**
for want of a real environment.
**Canonical source:** this document, plus `docs/ops/backup_restore.md` and
`docs/v2_platform/runbooks/e8_restore_runbook.md`, which already define the
procedure this epic must prove.

## Context and problem

Backup is in better shape than the rest of this program: `BackupManager`
already captures SQLite, PostgreSQL, and the artifact store under one
self-describing, digest-verified manifest; failures are recorded durably at
`AUTODEV_BACKUP_STATUS_PATH`, exposed as Prometheus gauges, and alerted on.
The runbook covers per-component restore and a quarterly drill.

Three gaps remain, and two of them are created by this program.

First, coverage. Every table E50 adds is new, and `plan_step_state` was in a
file the manifest never knew about. A backup that silently omits a table is
worse than no backup, because it is trusted.

Second, validation. Criterion 6 is Open because there is no staging
environment; the PostgreSQL and MinIO restore test variants auto-skip when the
services are absent, so a green local run proves nothing. E57-S4 gives this
epic the real environment it needs.

Third, the RPO mechanism. Reference §13.9 specifies "periodic base backups +
continuous WAL archiving (PITR)". The runbook meets RPO ≤ 5 min with a
five-minute `pg_dump` cron instead. That is a defensible engineering choice,
but it is an undocumented divergence from the stated architecture, and it
should be either implemented as specified or recorded as a deliberate
deviation.

## Evidence in code and documentation

- `docs/ops/backup_restore.md` — RPO ≤ 5 min, RTO ≤ 30 min; use the
  `BackupManager` CLI, not raw `pg_dump`, so all components share one
  manifest; a configured component whose CLI tool is missing fails the whole
  backup closed.
- `backend/persistence/backup.py:66` —
  `SQLITE_SNAPSHOT_FILENAME = "state_store.sqlite3"`; `:270-272` and
  `:555-557` the SQLite snapshot and restore paths.
- `backend/persistence/backup_status.py` and
  `infrastructure/observability/prometheus-rules.yml` —
  `autodev_backup_*` gauges and the `AutoDevBackupNeverSucceeded` /
  `AutoDevBackupStale` / `AutoDevBackupFailing` alerts.
- `docs/v2_platform/runbooks/e8_restore_runbook.md` — §4.1 SQLite, §4.2
  PostgreSQL, §4.3 artifact store; §5 RTO measurement; §7 the periodic drill.
- `docs/v2_platform/beta_gap_analysis.md` §11 criterion 6 — **Open**, "No
  staging environment".
- `backend/plans/step_state.py:132` — the step-state file, referenced nowhere
  in `backend/persistence/backup.py`: outside every manifest until E55-S3.
- Reference `docs/architecture/v2_platform_reference.md` §13.9 — PITR and a
  standby replica, neither implemented.

## Objective

Make PostgreSQL the complete, provable source of relational state in backup
and restore: extend manifest coverage to every table this program adds, prove
restore into a clean environment automatically, and resolve the PITR
divergence explicitly.

## Key result

An empty environment is rebuilt entirely from a validated backup — schema,
data, secrets, artifacts, and vector indexes — and serves requests, with
measured RTO and no SQLite database left outside the manifest.

## Scope

- PostgreSQL as the complete relational source in backup.
- `pg_dump` / `pg_restore` behavior through `BackupManager`.
- MinIO/S3 artifacts.
- Manifest, hashes, and schema versions.
- Secrets and the pgvector extension and its indexes.
- Restore into a clean environment.
- Point-in-time restore where supported, or a recorded deviation.
- Automated periodic testing.
- Documented RTO and RPO.
- A disaster runbook.
- Proof that no parallel SQLite database is outside the backup.

## Out of scope

- Standby replicas and high availability — reference §13.9 mentions a standby
  to improve RTO; that is a deployment topology decision beyond Beta.
- The migration from SQLite to PostgreSQL (E58).
- Building CI infrastructure (E57); this epic defines what runs in it.
- Backup of anything Redis holds, which by design must be reconstructible
  from PostgreSQL (reference §13.4).

## Stories

### E59-S1 — Complete manifest coverage

Subtasks:
- `E59-S1-T1`: extend backup coverage to every table E50 added, and assert
  coverage programmatically — enumerate the destination schema and fail if a
  table is present in the database but absent from the manifest, so the next
  new table cannot be silently omitted.
- `E59-S1-T2`: confirm plan step state is captured now that E55-S3 moved it,
  and assert no stray `.db` file exists outside the manifest in either
  profile.
- `E59-S1-T3`: record the pgvector extension, its version, and index state in
  the manifest, so a restore target that lacks the extension is detected
  before restore rather than during it.

| Criterion | Detail |
| --- | --- |
| Functional | Manifest covers every relational table plus artifacts, secrets, and extension state |
| Non-functional | Coverage is asserted by enumeration, not by a hand-maintained list |
| DoR (specific) | E50 and E55-S3 merged |
| DoD (specific) | A deliberately added table failing the coverage assertion until included |
| Dependencies | E8-S4, E50, E55-S3 |

### E59-S2 — Restore into a clean environment

Subtasks:
- `E59-S2-T1`: an automated restore drill into a genuinely empty environment
  — no pre-existing volume, schema, or bucket — closing the "no staging
  environment" gap behind criterion 6.
- `E59-S2-T2`: verify functionally after restore, not just structurally:
  serve requests, resolve a secret, resolve an artifact pointer, and execute
  a vector query, since the HNSW index must be usable and not merely present.
- `E59-S2-T3`: measure and record RTO from the drill, and schedule the drill
  to run periodically rather than only on demand.

| Criterion | Detail |
| --- | --- |
| Functional | A clean environment is rebuilt from backup and serves requests, including secrets, artifacts, and vector search |
| Non-functional | RTO measured against the ≤ 30 min target with real numbers, not asserted |
| DoR (specific) | E59-S1 merged; E57-S4 merged (a real environment exists) |
| DoD (specific) | Drill output with measured RTO and post-restore functional checks |
| Dependencies | E59-S1, E57-S4 |

### E59-S3 — RPO mechanism, deviation and runbook

Subtasks:
- `E59-S3-T1`: resolve the PITR divergence — either implement continuous WAL
  archiving as reference §13.9 specifies, or record a deliberate deviation
  documenting that RPO is met by five-minute base backups, with its
  consequences stated. Do not leave the architecture and the runbook
  disagreeing silently.
- `E59-S3-T2`: verify the RPO claim by measurement — the observed worst-case
  data loss window under the configured schedule — rather than by assertion.
- `E59-S3-T3`: update the disaster runbook for a PostgreSQL-primary
  deployment, and update `docs/ops/backup_restore.md` and the E8 restore
  runbook for the new coverage.

| Criterion | Detail |
| --- | --- |
| Functional | The RPO mechanism is implemented or the deviation is explicitly recorded; the runbook matches the implementation |
| Non-functional | RPO and RTO are measured numbers with a stated method, following the E35 "fact vs. recommendation" discipline |
| DoR (specific) | E59-S2 merged |
| DoD (specific) | Measured RPO/RTO recorded; runbook and architecture consistent or the deviation documented |
| Dependencies | E59-S2 |

## Contracts and decisions

### Architectural decisions required

- No new ADR is required if E59-S3-T1 implements PITR as already specified in
  reference §13.9.
- If the deliberate deviation is chosen instead — RPO met by frequent base
  backups rather than continuous WAL archiving — that **is** a durable
  architectural decision and needs its own ADR at that time, superseding the
  §13.9 expectation for the Beta deployment topology. The choice is made in
  E59-S3-T1's DoR, not assumed here.

### Security and multitenancy

- Backups contain ciphertext secrets and every tenant's data in one artifact;
  backup storage must be treated with the same sensitivity as the database.
- The manifest must not contain credentials or connection strings; the
  existing status file is already sanitized and `0600`, and that posture
  extends here.
- Restore is cross-tenant by nature and is an operator action, never exposed
  through the API.
- A restore target lacking the pgvector extension must fail before restore,
  not leave a half-restored database (E59-S1-T3).

### Migration strategy

- Schema version is recorded in the manifest, and restore refuses a target
  whose code is older than the backup's schema — the same posture
  `SchemaVersionMismatchError` already enforces for migrations.
- No new migrations in this epic.

### Compatibility and rollback

- SQLite backup continues to work for local-first installs; a component that
  does not apply is reported `skipped`, and that behavior is preserved.
- Rollback is reverting the coverage and drill changes; backup capability is
  never removed, only extended.

## Testing and observability

Tests required:
- Coverage assertion, including the negative control of a deliberately added
  uncovered table.
- No stray `.db` file outside the manifest in either profile.
- Full restore into a clean environment.
- Post-restore functional checks: requests, secret resolution, artifact
  resolution, vector query.
- RTO measurement.
- RPO measurement under the configured schedule.
- Restore refusing a target without pgvector, and a schema-version mismatch.

Observability:
- The existing `autodev_backup_*` gauges and alerts stay authoritative.
- Drill results — success, measured RTO — are recorded durably so the
  quarterly drill in the E8 runbook has an evidence trail rather than a
  memory.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| A new table silently omitted from backup | Trusted backup with missing data, discovered only during a real recovery | Enumeration-based coverage assertion with a negative control (E59-S1-T1) |
| Restore succeeds structurally but the system does not work | False confidence in recovery | Functional post-restore checks, including a vector query (E59-S2-T2) |
| PITR divergence left unresolved | Architecture and runbook disagree; RPO claim unfounded | E59-S3-T1 forces an explicit choice, with an ADR if the deviation is chosen |
| RPO/RTO claimed rather than measured | A Beta criterion marked met without evidence | Both measured with a stated method (E59-S3-T2), per the E35 evidence discipline |
| Restore target lacks pgvector | Half-restored database | Extension state in the manifest, checked before restore (E59-S1-T3) |

## DoR / DoD

- **DoR:** E50, E55-S3, and E57-S4 merged; the PITR-versus-deviation decision
  made; a clean environment available for the drill.
- **DoD:** all three story DoDs met; manifest coverage asserted by
  enumeration; a clean-environment restore serving requests with measured
  RTO; RPO mechanism resolved and documented; runbooks updated; Beta
  criterion 6 supported by named evidence;
  `docs/v2_platform/progress.md` updated; no push or PR without explicit
  authorization.

## Exit evidence

1. Coverage assertion output, including the negative control.
2. Clean-environment restore output with measured RTO.
3. Post-restore functional check output: request, secret, artifact, vector
   query.
4. Measured RPO with the method stated.
5. Updated runbooks, and an ADR if the PITR deviation was chosen.

## Affected documents and code

Documents: `docs/ops/backup_restore.md`,
`docs/v2_platform/runbooks/e8_restore_runbook.md`,
`docs/v2_platform/beta_gap_analysis.md` (criterion 6 evidence),
`docs/v2_platform/progress.md`, `docs/feature_matrix.md` (backup rows),
possibly a new ADR under `decisions/`.

Code: `backend/persistence/backup.py`, `backend/persistence/backup_status.py`,
`infrastructure/observability/prometheus-rules.yml` if alert thresholds
change, `.github/workflows/` for the scheduled drill.
