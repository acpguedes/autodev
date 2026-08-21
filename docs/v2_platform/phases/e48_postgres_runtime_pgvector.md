# E48 — PostgreSQL Runtime with pgvector

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/4
**Depends on:** E0-S3 (PostgreSQL state store, ADR-001), E7-S2 (pgvector
embeddings, ADR-011), E34-S2 (`backend/ops/doctor.py` preflight contract)
**Enables:** every other epic in the PostgreSQL Production Completeness
program — E50's migrations cannot be applied, and E57's CI job cannot boot,
until the `prod` runtime can actually satisfy `CREATE EXTENSION vector`.
**Canonical source:** this document, from a direct read of the current tree
(`d07b746`): `backend/persistence/migrations/postgres_versions.py:253` runs
`CREATE EXTENSION IF NOT EXISTS vector` unconditionally on every
`PostgresStore()` construction, while `infrastructure/docker-compose.yml:116`
ships stock `postgres:16-alpine`, which does not bundle the extension.

## Context and problem

ADR-001 made PostgreSQL the default production state store and ADR-011 chose
an HNSW index over `code_embeddings.embedding` for semantic retrieval. Both
decisions are implemented in code. Neither is reachable from the runtime the
project actually ships: the Compose `prod` profile starts a PostgreSQL image
without `pgvector`, so the fourth PostgreSQL migration aborts and the store
never finishes initializing.

The failure is also late and unhelpful. Nothing checks the extension before
the API starts, so the first symptom is a migration error during store
construction rather than a named preflight failure. Managed PostgreSQL
providers make this worse: there the application role frequently cannot run
`CREATE EXTENSION` at all, so an unconditional `CREATE EXTENSION` inside a
migration is the wrong place for the statement even when the extension is
available.

## Evidence in code

- `backend/persistence/migrations/postgres_versions.py:253` —
  `conn.execute("CREATE EXTENSION IF NOT EXISTS vector")` inside
  `_pg_m4_create_code_embeddings_table`, migration #4 of
  `POSTGRES_STORE_MIGRATIONS`.
- `backend/persistence/migrations/postgres_versions.py:256-271` —
  `embedding vector(128) NOT NULL` plus
  `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`.
  `_CODE_EMBEDDING_DIMENSION = 128` at `:240`.
- `backend/persistence/migrations/postgres_versions.py:281-291` — the down
  migration drops the table but deliberately leaves the extension installed.
- `infrastructure/docker-compose.yml:116` — `image: postgres:16-alpine`;
  `:117` `profiles: ["prod", "postgres"]`. No `pgvector/pgvector:*` image
  reference exists anywhere in the repository.
- `backend/persistence/postgres_adapter/store.py:52-54` — migrations run on
  store construction, so the failure surfaces at first use, not at boot.
- `backend/ops/doctor.py` — has a `database` check, but no check for server
  version, extension presence, extension usability, or index validity.
- `backend/repository/embeddings/pgvector_store.py:26-30` — the `pgvector`
  Python package is an *optional* lazy import with a text-literal fallback,
  so a missing client library degrades silently and is a separate concern
  from the missing server-side extension.
- `backend/requirements.txt:18` — `pgvector>=0.3` is declared.

## Objective

Make the `prod` runtime able to satisfy what the code already requires:
PostgreSQL 16 with a usable `vector` extension and a valid HNSW index, on
both the self-hosted Compose stack and managed providers, with failures
reported by a named preflight check before the API accepts traffic.

## Key result

`docker compose --profile prod up` starts from an empty volume, applies all
PostgreSQL migrations including `_pg_m4`, and serves a real vector query
through `GET /v2/context` hybrid retrieval. On a runtime that cannot satisfy
the requirement, the process fails closed at preflight with a message naming
the missing capability.

## Scope

- A pgvector-capable PostgreSQL 16 runtime for the Compose `prod` and
  `postgres` profiles: either a pinned upstream image or a versioned image
  built in `infrastructure/docker/`.
- Compatibility between the PostgreSQL major version and the pgvector
  version, pinned and documented.
- Extension provisioning separated from schema migration, with a path for
  managed providers where the application role lacks `CREATE EXTENSION`.
- Preflight and readiness checks: connectivity, minimum server version,
  `vector` extension present, extension usable by the application role, and
  the HNSW index present and valid.
- Fail-closed behavior before the API starts.
- Documentation of extension install, upgrade, and rollback.

## Out of scope

- Any change to the 13 missing domain tables (E50) or to the stores that
  refuse a PostgreSQL URL (E51-E55).
- Connection pooling and timeouts (E60).
- Retrieval quality benchmarking — this epic proves the vector path
  *executes*, not that recall or p95 meet a target. The hybrid-retrieval
  benchmark stays the open Beta criterion it already is.
- Changing the embedding dimension or the index type chosen by ADR-011.

## Stories

### E48-S1 — pgvector-capable PostgreSQL runtime

Subtasks:
- `E48-S1-T1`: choose and pin the runtime — upstream `pgvector/pgvector:pg16`
  or a versioned image built from `infrastructure/docker/` — and record the
  choice plus the managed-provider posture in ADR-024.
- `E48-S1-T2`: replace `image: postgres:16-alpine` in
  `infrastructure/docker-compose.yml:116` for both the `prod` and `postgres`
  profiles; keep the existing healthcheck, volume, and password handling
  unchanged.
- `E48-S1-T3`: pin the PostgreSQL major version against the pgvector version
  and state the supported pairs, so an image bump cannot silently move both.

| Criterion | Detail |
| --- | --- |
| Functional | `--profile prod up` from an empty `autodev_postgres` volume completes all 7 PostgreSQL migrations, `_pg_m4` included |
| Non-functional | Image and extension versions are pinned, not floating tags; existing healthcheck and credential validation behavior unchanged |
| DoR (specific) | ADR-024 drafted |
| DoD (specific) | A from-scratch `prod` bring-up applies migration 4 and creates the HNSW index; documented version pairs |
| Dependencies | E0-S3 |

### E48-S2 — Extension provisioning outside the migration

Subtasks:
- `E48-S2-T1`: move `CREATE EXTENSION IF NOT EXISTS vector` out of
  `_pg_m4_create_code_embeddings_table` into an explicit provisioning step,
  so schema migration no longer requires extension-creation privileges.
- `E48-S2-T2`: support managed providers where the application role cannot
  create extensions — detect an already-installed extension and proceed;
  when it is absent and cannot be created, fail with an actionable message
  naming the required operator action rather than a raw `psycopg` error.
- `E48-S2-T3`: keep the existing migration list append-only and its numbering
  intact (`postgres_versions.py:8` — "never edit or reorder"): the change
  must preserve the recorded `schema_version` semantics for databases that
  already applied migration 4.

| Criterion | Detail |
| --- | --- |
| Functional | Schema migration succeeds against a database where `vector` is pre-installed and the app role has no `CREATE EXTENSION` privilege |
| Non-functional | No renumbering or rewriting of existing migrations; already-migrated databases are unaffected |
| DoR (specific) | E48-S1 merged |
| DoD (specific) | Tests covering three cases: extension absent and creatable, absent and not creatable, already present |
| Dependencies | E48-S1 |

### E48-S3 — Preflight and readiness checks

Subtasks:
- `E48-S3-T1`: extend `backend/ops/doctor.py` with ordered, typed checks for
  PostgreSQL connectivity, minimum server version, `vector` extension
  presence, extension usability by the application role, and HNSW index
  presence/validity — following the existing skip-dependents-on-failure
  pattern.
- `E48-S3-T2`: wire the same checks into `backend/ops/bootstrap.py` so the
  `prod` profile fails closed *before* the API starts serving, instead of at
  first store construction.
- `E48-S3-T3`: expose extension and index status on the readiness surface so
  an unhealthy database is visible to an orchestrator, not only in logs.

| Criterion | Detail |
| --- | --- |
| Functional | Each of the five conditions produces a distinct, named failure; `prod` refuses to serve when any is unmet |
| Non-functional | Checks add no per-request cost and run once at startup; no secret material in check output |
| DoR (specific) | E48-S2 merged |
| DoD (specific) | Unit tests asserting one distinguishable failure per condition, plus a fail-closed boot test |
| Dependencies | E34-S2 |

### E48-S4 — Extension lifecycle documentation

Subtasks:
- `E48-S4-T1`: document install, upgrade, and rollback of `pgvector`,
  including the managed-provider path where an operator must pre-install it.
- `E48-S4-T2`: document the supported PostgreSQL/pgvector version pairs and
  what to do when a provider offers only a different pgvector version.
- `E48-S4-T3`: record in `docs/config.md` that the `prod` profile requires a
  pgvector-capable image, and correct the Compose reference in
  `docs/ops/backup_restore.md` if the image name it implies has changed.

| Criterion | Detail |
| --- | --- |
| Functional | An operator can install, upgrade, and roll back the extension from the documentation alone |
| Non-functional | No sample passwords introduced, consistent with the existing rule in `docs/ops/backup_restore.md` |
| DoR (specific) | E48-S1 merged (the chosen runtime is known) |
| DoD (specific) | Docs updated and internally consistent with the Compose file |
| Dependencies | E48-S1 |

## Contracts and decisions

### Architectural decisions required

- **ADR-024 — pgvector runtime image and managed-provider strategy**
  (`decisions/ADR-024-pgvector-runtime-image.md`, `Proposed`): which runtime
  the project ships, how the extension is provisioned, and what is required
  of a managed provider. Decided within E48-S1.
- No change to ADR-011 (HNSW over cosine) or ADR-001 — this epic makes them
  executable, it does not revisit them.

### Security and multitenancy

- RLS on `code_embeddings` already exists
  (`postgres_versions.py:272-278`) and must survive the provisioning change:
  moving `CREATE EXTENSION` out of the migration must not move or weaken the
  `ENABLE`/`FORCE ROW LEVEL SECURITY` statements or the
  `code_embeddings_tenant_isolation` policy.
- Preflight output must not include connection strings or credentials.
- Extension creation is an operator-privileged action; the application role
  should not require superuser in the target design.

### Migration strategy

- Existing migrations stay append-only and are never renumbered.
- Extension provisioning becomes a separate, idempotent step executed before
  the migration runner.
- Databases that already applied `_pg_m4` must not be re-migrated or
  downgraded by this change.

### Compatibility and rollback

- SQLite/local is untouched: it has no vector path today and gains none here.
- Rollback is an image revert plus reverting the provisioning split; because
  the down migration deliberately leaves the extension installed
  (`:281-291`), reverting the image on an existing volume does not corrupt
  data, but does make migration 4 unrunnable again — state this explicitly
  in the rollback documentation.

## Testing and observability

Tests required:
- From-scratch `prod` bring-up applying all migrations (moves to CI in E57).
- A real vector query returning ordered results through the retrieval path.
- Preflight matrix: each of the five conditions failing independently.
- Provisioning matrix: extension absent/creatable, absent/not creatable,
  already present.
- Regression: RLS still enforced on `code_embeddings` after the split.

Observability:
- Named preflight results surfaced on readiness.
- Extension version and index validity reported once at startup.
- No new per-request metrics; pool and query metrics belong to E60.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Chosen image lags PostgreSQL security patches | Unpatched production database | Pin explicit version pairs and state the upgrade procedure (E48-S1-T3, E48-S4-T2) |
| Managed provider offers a different pgvector version | Index or operator class unavailable | Preflight asserts usability, not just presence (E48-S3-T1); documented supported pairs |
| Splitting `CREATE EXTENSION` out of migration 4 breaks already-migrated databases | Existing installs fail to start | Preserve migration numbering and recorded `schema_version`; explicit test for an already-migrated database (E48-S2-T3) |
| Image change silently alters locale/collation | Index or ordering differences | Bring up from an empty volume in CI and compare migration outcomes (E57-S1) |

## DoR / DoD

- **DoR:** ADR-024 drafted; the current failure reproduced (a `prod`
  bring-up on `postgres:16-alpine` aborting on migration 4).
- **DoD:** all four story DoDs met; `prod` boots from empty and serves a real
  vector query; preflight fails closed with named causes; extension lifecycle
  documented; ADR-024 moved to `Accepted`; `docs/v2_platform/progress.md`
  updated; no push or PR without explicit authorization.

## Exit evidence

1. Command output of a from-scratch `--profile prod` bring-up showing all 7
   migrations applied.
2. Output of a real vector query (non-empty, ordered) against the running
   stack.
3. Preflight output for each of the five failure conditions.
4. ADR-024 at `Accepted` with the chosen image and version pairs recorded.

## Affected documents and code

Documents: `docs/config.md`, `docs/ops/backup_restore.md` (Compose
reference), `docs/feature_matrix.md` (pgvector row),
`docs/v2_platform/progress.md`, `decisions/ADR-024-pgvector-runtime-image.md`,
`decisions/README.md`.

Code: `infrastructure/docker-compose.yml`, `infrastructure/docker/` (if a
built image is chosen), `backend/persistence/migrations/postgres_versions.py`,
`backend/persistence/postgres_adapter/store.py`, `backend/ops/doctor.py`,
`backend/ops/bootstrap.py`.
