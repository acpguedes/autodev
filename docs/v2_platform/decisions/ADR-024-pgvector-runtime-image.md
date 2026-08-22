# ADR-024: pgvector Runtime Image and Extension Provisioning

- **Status:** Accepted
- **Date:** 2026-08-21
- **Authors:** AutoDev platform team
- **Related epic:** E48
- **Supersedes/Relates to:** ADR-001 (PostgreSQL as default production state
  store), ADR-011 (pgvector HNSW index for code chunk embeddings)

## Context

ADR-011 selected an HNSW index over `code_embeddings.embedding`, and the
migration implementing it runs `CREATE EXTENSION IF NOT EXISTS vector`
unconditionally at
`backend/persistence/migrations/postgres_versions.py:253`, inside
`_pg_m4_create_code_embeddings_table`. Migrations execute on store
construction (`backend/persistence/postgres_adapter/store.py:52-54`).

The Compose `prod` and `postgres` profiles start
`postgres:16-alpine` (`infrastructure/docker-compose.yml:116-117`). That
image does not bundle `pgvector`. No `pgvector/pgvector:*` reference exists
anywhere in the repository.

Consequently the fourth PostgreSQL migration cannot succeed against the stack
the project ships, and the failure appears as a migration error at first
store use rather than as a named startup check. Nothing verifies the server
version, the extension's presence, the application role's ability to use it,
or the validity of the HNSW index before the API begins serving.

A second constraint applies beyond self-hosting. On managed PostgreSQL
providers the application role frequently cannot execute `CREATE EXTENSION`
at all, even when the extension is available for installation by an operator.
An unconditional `CREATE EXTENSION` inside a schema migration is therefore
the wrong location for the statement regardless of which image is chosen: it
couples schema migration to a privilege the application should not need.

## Decision

1. **Ship a pgvector-capable PostgreSQL 16 runtime** for the Compose `prod`
   and `postgres` profiles, replacing `postgres:16-alpine` with the pinned
   upstream image **`pgvector/pgvector:0.8.3-pg16`**
   (`infrastructure/docker-compose.yml:116`). Chosen over a self-built image
   under `infrastructure/docker/` because the upstream image is maintained
   by the pgvector project itself, tracks PostgreSQL security patches, and
   needs no additional build step in CI or Compose.
2. **Pin the PostgreSQL major version together with the pgvector version**,
   and document the supported pairs, so an image bump cannot silently move
   both at once. CI (E57-S1-T1) uses the same pinned image as Compose, so the
   two cannot drift. Supported pair for this decision: **PostgreSQL 16 /
   pgvector 0.8.3** (tag `0.8.3-pg16`). A future bump to a newer PostgreSQL
   major or pgvector release updates this pin explicitly, in the same commit
   as the compatibility statement in `docs/config.md`, rather than floating.
3. **Separate extension provisioning from schema migration.**
   `CREATE EXTENSION` moves out of `_pg_m4` into an explicit provisioning
   step that runs before the migration runner. Existing migrations keep their
   numbering and recorded `schema_version` — the list stays append-only, per
   `postgres_versions.py:8`.
4. **Do not require the application role to be able to create extensions.**
   Provisioning detects an already-installed extension and proceeds. When the
   extension is absent and cannot be created, startup fails with an
   actionable message naming the operator action required, not a raw
   `psycopg` error.
5. **Verify capability at preflight, and fail closed.** Five ordered checks —
   connectivity, minimum server version, extension present, extension usable
   by the application role, HNSW index present and valid — extend
   `backend/ops/doctor.py` and gate startup through
   `backend/ops/bootstrap.py`. Each produces a distinguishable failure.
6. **Presence is not sufficient; usability is checked.** A provider offering
   a different pgvector version may lack the operator class the index
   requires, so the check exercises usability rather than reading a catalog
   entry.

## Alternatives considered

**Keep `CREATE EXTENSION` inside the migration and only change the image.**
Simplest, and would fix self-hosted Compose. Rejected because it leaves
managed providers broken: schema migration would still demand a privilege the
application role often lacks, and the failure would still surface late and
unclearly.

**Make the vector path optional and degrade when the extension is absent.**
Attractive because `backend/repository/embeddings/pgvector_store.py:26-30`
already treats the *client* library as optional with a text-literal fallback.
Rejected for the server-side extension: reference §13.5 makes pgvector the
production retrieval path, and `backend/api/routers/context.py:92,157`
already errors when the store is not PostgreSQL. Silent degradation would
turn a deployment error into an invisible, permanent quality regression.

**Use a dedicated vector service instead of pgvector.** Rejected — it
reverses ADR-011 and reference §13.1's explicit OSS-first decision to keep
embeddings inside PostgreSQL until scale requires otherwise. Nothing in the
current evidence indicates that scale.

**Run migrations as a superuser.** Rejected: it grants the application far
more privilege than it needs, and is impossible on many managed providers.

## Consequences

### Positive

- The `prod` profile becomes able to complete its own migrations, which it
  cannot today.
- Managed PostgreSQL becomes a supported deployment target rather than an
  untested assumption.
- Failures move from a late, opaque migration error to a named preflight
  check with an actionable message.
- CI and Compose share one pinned image, removing a class of
  "works-in-CI-only" divergence.

### Negative / trade-offs

- A pgvector-capable image is larger than `postgres:16-alpine` and may lag
  upstream PostgreSQL patch releases; the pinned version pairs must be
  reviewed as part of routine dependency maintenance.
- Provisioning becomes a distinct startup step, adding one more thing that
  can fail — deliberately, since it currently fails later and less clearly.
- Operators on managed providers acquire a documented prerequisite: install
  the extension before first boot.

### Contract impact

None on `/v2`. The change is confined to the runtime image, startup
provisioning, and preflight checks. `_CODE_EMBEDDING_DIMENSION = 128`
(`postgres_versions.py:240`), the HNSW index definition, and the
`code_embeddings` RLS policy (`:272-278`) are all unchanged.

## Rollback plan

Revert the Compose image and the provisioning split. Because the down
migration for `code_embeddings` deliberately leaves the extension installed
(`postgres_versions.py:281-291`), reverting the image on an existing volume
does not corrupt data — but it does make migration 4 unrunnable again on a
fresh volume, restoring the current defect. Both consequences are documented
in the E48-S4 rollback notes.

Databases that already applied migration 4 are unaffected by either
direction: the provisioning split preserves migration numbering and the
recorded `schema_version`.

## References

- `backend/persistence/migrations/postgres_versions.py:240-291`
- `infrastructure/docker-compose.yml:115-130`
- `backend/persistence/postgres_adapter/store.py:52-54`
- `backend/ops/doctor.py`, `backend/ops/bootstrap.py`
- `backend/repository/embeddings/pgvector_store.py:26-56`
- `docs/architecture/v2_platform_reference.md` §13.1, §13.5, §11.4
- `docs/v2_platform/phases/e48_postgres_runtime_pgvector.md`
- `docs/v2_platform/postgres_production_completeness.md`
