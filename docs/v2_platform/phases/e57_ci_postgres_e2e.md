# E57 — CI and Real PostgreSQL E2E

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/4
**Depends on:** E48 (a pgvector-capable runtime), E56 (the contract suite CI
must run), E50-E55 (the behavior the E2E exercises)
**Enables:** every claim this program makes to be continuously verified
rather than verified once by hand, and closes the structural reason the
current divergence went unnoticed.
**Canonical source:** this document, from a direct read of
`.github/workflows/`: there is **no `services:` block in any workflow**, so no
PostgreSQL, Redis, or MinIO instance has ever run in CI.

## Context and problem

Four workflows exist and none of them starts a database. `ci-backend.yml`
runs `pytest tests backend/tests` on a single Python 3.11 with an 85% coverage
floor, against whatever SQLite the tests create. Every PostgreSQL code path
— both adapter packages, all seven migrations, RLS, pgvector — is exercised
only through monkeypatched fakes.

This is the root cause of the program, not a side effect of it. Five stores
could refuse PostgreSQL, thirteen tables could be missing from the migration
list, and migration 4 could be unrunnable against the shipped Compose image,
all while CI stayed green. Fixing the stores without fixing CI would leave the
same blind spot in place for the next regression.

The Beta gate has two open criteria for the same reason: hybrid retrieval was
never benchmarked against a live PostgreSQL + pgvector, and backup/restore was
never validated in a real environment.

## Evidence in code

- `.github/workflows/` contains `ci-backend.yml`, `ci-e2e.yml`,
  `ci-evals.yml`, `ci-frontend.yml`. Searching all four for `services:`
  returns nothing.
- `.github/workflows/ci-backend.yml` — four flat jobs
  (`lint-typecheck`, `patch-validation`, `security-baseline`,
  `backend-tests`), all `ubuntu-latest`, all pinned to a single Python 3.11
  (`:21, :48, :68, :105`); `:115-117` `--cov-fail-under=85`. No matrix.
- `backend/tests/unit/persistence/test_postgres_store.py:73-92` — PostgreSQL
  behavior asserted against a monkeypatched `psycopg`.
- `infrastructure/docker-compose.yml:115-130` — the `postgres` service exists
  for local use under the `prod` and `postgres` profiles, and is the natural
  model for the CI service definition.
- `docs/v2_platform/beta_gap_analysis.md` §11 — criterion 2 (hybrid
  retrieval) and criterion 6 (backup/restore in staging) both **Open**, both
  for want of a live environment.
- PostgreSQL and MinIO backup/restore test variants auto-skip when the
  services are absent, so local green runs prove nothing about them.

## Objective

Run a real PostgreSQL 16 + pgvector in CI, apply migrations to an empty
database, execute the contract suite and a true `prod`-profile end-to-end flow
against it, and make that a required part of every pull request.

## Key result

Every pull request executes at least one real end-to-end flow in the `prod`
profile against PostgreSQL, Redis, and MinIO — including a real vector query,
two-tenant RLS enforcement, and a backup/restore round trip — with mocked
connections no longer accepted as PostgreSQL evidence.

## Scope

- A real PostgreSQL 16 + pgvector service in CI.
- Migrations applied to an empty database, plus schema upgrade and, where
  safe, rollback.
- Redis and MinIO where the flow requires them.
- A test matrix or separate jobs for `local`/SQLite and
  `prod`/PostgreSQL+pgvector+Redis+MinIO.
- Real `prod`-profile initialization.
- API end-to-end, vector search, two-tenant RLS, concurrency.
- Backup and restore.
- Useful diagnostics when a service fails to start.

## Out of scope

- Building the contract suite itself (E56).
- Performance SLOs and load testing (E60-S4).
- The retrieval recall/latency benchmark — this epic proves the vector path
  executes in CI; measuring recall and p95 against a target stays its own
  open Beta criterion.
- Multi-version PostgreSQL support; the matrix covers backends, not
  PostgreSQL majors.

## Stories

### E57-S1 — PostgreSQL service and migrations in CI

Subtasks:
- `E57-S1-T1`: add a PostgreSQL 16 + pgvector service to the backend
  workflow, using the image pinned by E48-S1 so CI and Compose cannot drift
  apart.
- `E57-S1-T2`: apply all migrations to an empty database as an explicit CI
  step, so a broken or unrunnable migration fails fast and visibly rather
  than inside a test.
- `E57-S1-T3`: exercise schema upgrade — migrate an older schema forward —
  and exercise `down` where it is safe, validating the reversibility E50
  claims.

| Criterion | Detail |
| --- | --- |
| Functional | CI starts a real PostgreSQL with a usable `vector` extension and applies all migrations from empty |
| Non-functional | The image is pinned to the same version pair as Compose; migration failures surface as their own step |
| DoR (specific) | E48-S1 merged (a pinned image exists) |
| DoD (specific) | CI run showing migrations applied from empty, plus an upgrade and a rollback |
| Dependencies | E48, E50 |

### E57-S2 — Backend test matrix

Subtasks:
- `E57-S2-T1`: split `backend-tests` into a matrix or two jobs —
  `local`/SQLite and `prod`/PostgreSQL — so both backends are exercised on
  every pull request.
- `E57-S2-T2`: run the E56 contract suite in both matrix legs, and make the
  PostgreSQL leg fail rather than skip when the service is unavailable,
  removing the silent-skip failure mode.
- `E57-S2-T3`: add Redis and MinIO services for the jobs that need them, so
  the `prod` leg validates against real dependencies rather than in-process
  substitutes.

| Criterion | Detail |
| --- | --- |
| Functional | Both matrix legs run on every pull request; the contract suite runs in both |
| Non-functional | A missing PostgreSQL fails the job; coverage thresholds preserved; no silent skips |
| DoR (specific) | E57-S1 and E56 merged |
| DoD (specific) | A pull request showing both legs green, and a deliberate service outage failing the PostgreSQL leg |
| Dependencies | E57-S1, E56 |

### E57-S3 — Production-profile end-to-end

Subtasks:
- `E57-S3-T1`: boot the real `prod` profile in CI — PostgreSQL, Redis, MinIO,
  `AUTODEV_PROFILE=prod` — passing the same `validate_profile` checks a real
  deployment does, including the non-default-password rule.
- `E57-S3-T2`: exercise an API end-to-end flow including a real vector query
  through hybrid retrieval, and a two-tenant RLS check asserting both
  directions of the boundary.
- `E57-S3-T3`: run the concurrency invariants from E51-E55 against the real
  stack, where multiple connections genuinely contend.

| Criterion | Detail |
| --- | --- |
| Functional | A real `prod` flow completes in CI: plan/approve/execute path, vector query, two-tenant isolation, concurrency invariants |
| Non-functional | The E2E uses the real profile validation path, not a relaxed test configuration; no default credentials |
| DoR (specific) | E57-S2 merged; E51-E55 merged |
| DoD (specific) | CI run of the full `prod` E2E, with vector-query and isolation output captured |
| Dependencies | E57-S2, E51-E55, E48 |

### E57-S4 — Backup, restore and diagnostics

Subtasks:
- `E57-S4-T1`: a CI backup/restore round trip against the real stack, closing
  the "no staging environment" gap behind open Beta criterion 6 — reusing the
  existing `BackupManager` CLI rather than raw `pg_dump`.
- `E57-S4-T2`: assert the restored environment is functional, not merely that
  the command exited zero — a session/run listing smoke test after restore,
  as `docs/ops/backup_restore.md` already prescribes manually.
- `E57-S4-T3`: diagnostics on failure — service logs, migration state, and
  the failing check surfaced in the CI output so a red build is actionable
  without reproducing locally.

| Criterion | Detail |
| --- | --- |
| Functional | Backup and restore complete in CI and the restored environment serves requests |
| Non-functional | A failed service produces actionable logs; the auto-skip behavior is gone for these variants |
| DoR (specific) | E57-S3 merged |
| DoD (specific) | CI run showing backup, restore, and a post-restore smoke test |
| Dependencies | E57-S3, E8-S4 |

## Contracts and decisions

### Architectural decisions required

- No new ADR. This epic operationalizes existing decisions.
- One policy worth stating in the epic: **mocked connections do not count as
  PostgreSQL evidence.** Fakes remain acceptable for fast unit tests, but no
  Beta criterion may be marked met on their basis. This mirrors the "fact vs.
  recommendation" discipline E35-S1-T3 established for the gate evidence map.

### Security and multitenancy

- The `prod` E2E must use real profile validation, including the rejection of
  known-default PostgreSQL passwords (E11-S4) — a CI job that weakens
  validation to boot faster would defeat the purpose.
- CI credentials must be generated per run, never a checked-in value; the
  repository's existing rule of no sample passwords in documentation extends
  to workflow files.
- The two-tenant RLS check is the continuous proof of the isolation property
  E50-S4 establishes.

### Migration strategy

- CI applies migrations to an empty database on every run, so schema drift is
  detected immediately.
- The upgrade path is exercised separately from the from-empty path, because
  the two fail differently.

### Compatibility and rollback

- The SQLite leg must stay green throughout; local-first is a supported
  configuration, not a legacy one.
- Rollback is reverting the workflow changes; no runtime behavior depends on
  this epic.
- Longer CI times are an accepted cost and are stated as such rather than
  discovered.

## Testing and observability

Tests required:
- Migrations from empty; upgrade; rollback where safe.
- The E56 contract suite in both matrix legs.
- `prod`-profile boot with real validation.
- API end-to-end including a real vector query.
- Two-tenant RLS, both directions.
- Concurrency invariants against real connections.
- Backup, restore, and post-restore smoke test.

Observability:
- CI output must distinguish "passed on both backends" from "passed on
  SQLite, PostgreSQL skipped".
- Service logs and migration state are attached on failure.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| CI runtime grows enough that contributors bypass it | The blind spot returns by another route | Split into parallel jobs rather than one long job; keep the SQLite leg fast for quick feedback |
| Flaky service startup | Distrusted, eventually ignored CI | Health-gated startup mirroring the Compose healthchecks; diagnostics in E57-S4-T3 |
| CI image drifts from the Compose image | CI proves something production does not run | Both pinned by E48-S1 to the same version pair (E57-S1-T1) |
| The `prod` E2E relaxes validation to pass | A green E2E that does not represent production | E57-S3-T1 requires the real `validate_profile` path |
| Coverage floor blocks the matrix split | Job fails for unrelated reasons | Decide coverage aggregation across legs as part of E57-S2 |

## DoR / DoD

- **DoR:** E48-S1 merged (pinned image); E56 merged (a suite to run);
  E51-E55 merged for the E2E scope.
- **DoD:** all four story DoDs met; every pull request runs both matrix legs
  and at least one real `prod` E2E; backup/restore validated in CI; no silent
  skips; `docs/v2_platform/progress.md` updated; no push or PR without
  explicit authorization.

## Exit evidence

1. A CI run showing migrations applied from an empty PostgreSQL, plus an
   upgrade and a rollback.
2. A CI run showing both matrix legs green and the contract suite executed in
   both.
3. `prod` E2E output including a real vector query result and two-tenant
   isolation.
4. Backup/restore round-trip output with a post-restore smoke test.
5. A deliberately broken service producing actionable diagnostics.

## Affected documents and code

Documents: `docs/v2_platform/progress.md`,
`docs/v2_platform/beta_gap_analysis.md` (criteria 2 and 6 evidence),
`CONTRIBUTING.md` (required checks), `docs/feature_matrix.md` (CI rows).

Code: `.github/workflows/ci-backend.yml`, `.github/workflows/ci-e2e.yml`,
`infrastructure/docker-compose.yml` (shared image pin), `Makefile` if new
targets are added.
