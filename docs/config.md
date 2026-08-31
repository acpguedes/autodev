# Configuration

AutoDev uses a typed `Settings` object as the declarative runtime configuration
source for v2 platform work. E0 commands should validate configuration inside
the backend container:

```bash
make container-shell
python -m backend.cli config validate --profile local
```

## Profiles

- `local`: default profile for the container-first developer workflow. Requires
  SQLite and the `stub`, `ollama`, or configured `openai` provider.
- `prod`: production profile. Requires PostgreSQL, Redis, and MinIO/S3 settings
  to be present before boot.

Configuration precedence is:

1. safe defaults from `backend/config/settings.py`;
2. JSON settings file from `AUTODEV_SETTINGS_FILE`;
3. environment variables.

Secrets are redacted from API/CLI inspection surfaces.

## Local Container Defaults

The Compose backend service sets:

```env
AUTODEV_PROFILE=local
DATABASE_URL=sqlite:////data/autodev.db
LLM_PROVIDER=stub
AUTODEV_CONFIG_PATH=/data/autodev.config.json
AUTODEV_PROJECT_ROOT=/workspace
AUTODEV_JOB_BACKEND=inprocess
STORAGE_BACKEND=local
AUTODEV_ARTIFACT_DIR=/data/artifacts
```

## Production-Like Storage Profile

The `prod` profile fails fast unless PostgreSQL, Redis, and MinIO/S3 are all
selected explicitly:

```env
AUTODEV_PROFILE=prod
DATABASE_URL=postgresql://autodev:<set outside git>@postgres:5432/autodev
AUTODEV_JOB_BACKEND=redis
AUTODEV_REDIS_URL=redis://redis:6379/0
STORAGE_BACKEND=s3
AUTODEV_MINIO_ENDPOINT=minio:9000
AUTODEV_MINIO_ACCESS_KEY=<set outside git>
AUTODEV_MINIO_SECRET_KEY=<set outside git>
```

Run the production-like local stack with:

```bash
docker compose -f infrastructure/docker-compose.yml --profile prod up --build backend-prod
```

> **PostgreSQL must be pgvector-capable (resolved 2026-08-22, E48/ADR-024).**
> The `prod`/`postgres` Compose profiles ship
> `pgvector/pgvector:0.8.3-pg16` (`infrastructure/docker-compose.yml:116`),
> which bundles the `vector` extension PostgreSQL 16 needs to satisfy
> `code_embeddings.embedding` (pgvector). Extension provisioning is a
> separate, idempotent step
> (`backend/persistence/postgres_adapter/vector_provisioning.py`) that runs
> before schema migration on every store construction: it detects an
> already-installed extension and proceeds without privilege, or attempts
> `CREATE EXTENSION` and fails with an actionable message if it cannot. The
> `prod` profile also fails closed at preflight — `backend/ops/doctor.py`
> checks server version, extension presence, extension usability, and HNSW
> index validity before the API accepts traffic (surfaced at `GET
> /readiness`, in addition to `autodev doctor`) — so a missing capability is
> a named startup failure, not a first-use migration error. See
> "PostgreSQL/pgvector extension lifecycle" below for install, upgrade, and
> rollback on a managed provider.
>
> **Known `prod` limitation (verified 2026-08-26).** Execution policy and
> execution environments cannot currently be constructed under
> `AUTODEV_PROFILE=prod`: their stores raise `ValueError` on a
> `postgresql://` URL (`backend/execution/policy.py:206`,
> `backend/environments/store.py:38`). `QuotaStore` (E51) and `SecretStore`
> (E52) are already ported onto the shared persistence contract and
> construct correctly under `prod`. `StepApprovalStore` (plan step state,
> E55) no longer diverts to a standalone SQLite file on a `postgresql://`
> URL either — it now resolves through the same configured State Store as
> every other domain store; see "Plan step state" below. Closing the
> remaining two stores is the subject of epics E49-E60 (E48's own scope — a
> pgvector-capable runtime — is resolved). Connection-pool and
> statement-timeout settings do not exist yet and are introduced by E60.

> **Plan step state (`AUTODEV_PLAN_STEP_STATE_DB`, E55).** Prior to E55,
> `StepApprovalStore` silently wrote per-step plan-approval state to a
> standalone SQLite file (`AUTODEV_PLAN_STEP_STATE_DB`, default
> `./autodev_plan_step_state.db`) whenever `DATABASE_URL` was unset or
> pointed at PostgreSQL — invisible to other replicas and absent from every
> backup manifest. E55 removed that fallback: the store now always resolves
> its connection through the configured State Store
> (`backend.persistence.database.get_store()`), the same dispatch every
> other `/v2` store uses, and `plan_step_state` lives under the same
> tenant-scoped, Row-Level-Security-enforced table on PostgreSQL that E50-S3
> created for it. `AUTODEV_PLAN_STEP_STATE_DB` still exists, but only as a
> local-SQLite convenience: it selects which file
> `backend.plans.step_state.StepApprovalStore(db_path=...)` opens when a
> caller (tests, or a one-off script) explicitly asks for a dedicated file
> rather than the configured store — it has no effect on where the
> production store connects, and it is never consulted under a
> `postgresql://` `DATABASE_URL`. A pre-E55 install's existing
> `./autodev_plan_step_state.db` (if any) is migrated by
> `python -m backend.persistence.step_state_migration`; the legacy file is
> retained, not deleted, so the migration can be re-run or the port reverted
> without data loss.

`autodev config validate --profile prod` uses the same settings validation as
startup. Missing Redis/MinIO settings, `AUTODEV_JOB_BACKEND` values other than
`redis`, or `STORAGE_BACKEND` values other than `s3` abort with an actionable
error before the API starts.

### PostgreSQL/pgvector extension lifecycle (E48-S4, ADR-024)

**Supported version pair:** PostgreSQL 16 with pgvector 0.8.3 (Compose image
tag `pgvector/pgvector:0.8.3-pg16`). The pair is pinned together — bumping
one without the other is not supported — and CI (E57) uses the same pinned
image as Compose so the two cannot drift.

**Self-hosted install (Compose).** Nothing to do: the `prod`/`postgres`
profiles already ship the pgvector-capable image, and
`provision_vector_extension()` creates the extension on first
`PostgresStore` construction if it is not already present.

**Managed provider install.** Provision a PostgreSQL 16 instance running (or
offering as an installable extension) pgvector 0.8.3, then have an operator
with sufficient privilege run once, before first boot:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

The application's own database role does not need — and should not be
granted — `CREATE EXTENSION` privilege. If the extension is absent and the
role cannot create it, startup fails at preflight
(`pgvector_extension_present`, surfaced by `autodev doctor` and `GET
/readiness`) with this same instruction, rather than a raw migration error.

**Upgrade.** Upgrading pgvector on an existing database is an operator
action (`ALTER EXTENSION vector UPDATE`) independent of application
deployment; run it during a maintenance window, then confirm
`pgvector_extension_usable` and `pgvector_hnsw_index` still report `ok` via
`autodev doctor` or `GET /readiness`. A provider that only offers a pgvector
version incompatible with the HNSW operator classes this codebase relies on
is not a supported pair — `pgvector_extension_usable` fails closed rather
than degrading silently.

**Rollback.** Reverting the Compose image (or an operator dropping the
extension) does not corrupt data: the down migration for `code_embeddings`
deliberately leaves the extension installed. On a fresh volume, reverting
the image restores the original defect (migration 4 cannot succeed) — this
is expected, not a regression, and preflight will report it as
`pgvector_extension_present: fail` rather than a late migration error.

## Artifact Storage (E8-S3)

### Backend selection

`STORAGE_BACKEND` selects the artifact payload backend: `local` writes files
under `AUTODEV_ARTIFACT_DIR`; `s3` targets MinIO/S3 using the
`AUTODEV_MINIO_*` settings. Both backends implement the same `ArtifactStore`
interface (`backend/artifacts/store.py`), so callers are backend-agnostic.

### Pointer semantics

Payload bytes live in the storage backend; the State Store only holds
*pointers*. `ArtifactPointerStore` (`backend/artifacts/pointers.py`) records
one row per artifact in the `artifacts` table — tenant, kind, bucket,
object key, `sha256`, size, content type, and free-form JSON context — with a
`UNIQUE (bucket, object_key)` constraint. Re-recording the same
`(bucket, object_key)` updates the existing pointer in place (upsert). The
pointer, not the payload, is the unit of listing, lookup, and lifecycle:
deleting an artifact removes the payload from the backend and then the
pointer row. Use `persist_artifact()` to upload a payload and record its
pointer in one step.

### Retention and cleanup

`cleanup_unreferenced_artifacts()` (`backend/artifacts/cleanup.py`) garbage
collects artifacts by *reference*: an object is removed only when no pointer
row references it **and** it is older than
`AUTODEV_ARTIFACT_RETENTION_DAYS` days (default `7`; `-1` disables cleanup
entirely and keeps objects forever). Referenced objects are never removed
regardless of age. Run it on a schedule via the CLI subcommand:

```bash
# preview what would be removed
python -m backend.cli artifacts-cleanup --dry-run
# example cron: daily at 03:30
30 3 * * * python -m backend.cli artifacts-cleanup
```

### Presigned URL expiration

MinIO/S3 download URLs issued by the store are presigned and expire after
`DEFAULT_PRESIGNED_URL_EXPIRY_SECONDS` (1 hour). Consumers must re-request a
URL rather than persisting one; the local backend serves paths that do not
expire.

## Environment Inventory

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTODEV_PROFILE` | `local` | Selects `local` or `prod` validation rules. |
| `AUTODEV_SETTINGS_FILE` | empty | Optional flat JSON settings file loaded below env vars. |
| `DATABASE_URL` | `sqlite:///./autodev.db` | State store connection URL. |
| `AUTODEV_POSTGRES_POOL_MIN_SIZE` | `1` | Minimum connections the process-local PostgreSQL pool keeps open (E60-S1). |
| `AUTODEV_POSTGRES_POOL_MAX_SIZE` | `10` | Maximum concurrent checked-out/open PostgreSQL connections (E60-S1). |
| `AUTODEV_POSTGRES_POOL_TIMEOUT_SECONDS` | `5.0` | Maximum wait for a pooled connection before raising a typed pool-exhaustion error (E60-S1). |
| `AUTODEV_POSTGRES_STATEMENT_TIMEOUT_MS` | `30000` | Per-session `statement_timeout`; a query running longer is canceled (SQLSTATE `57014`). `0` disables it (E60-S3). |
| `AUTODEV_POSTGRES_LOCK_TIMEOUT_MS` | `5000` | Per-session `lock_timeout`; a stuck lock wait aborts (SQLSTATE `55P03`). `0` disables it (E60-S3). |
| `AUTODEV_POSTGRES_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS` | `60000` | Per-session `idle_in_transaction_session_timeout`; an abandoned open transaction is terminated (SQLSTATE `25P03`). `0` disables it (E60-S3). |
| `AUTODEV_POSTGRES_RETRY_MAX_ATTEMPTS` | `3` | Bounded retry attempts for transient PostgreSQL deadlock/serialization-failure errors around advisory-lock-guarded writes (E60-S3). |
| `AUTODEV_POSTGRES_RETRY_BASE_DELAY_SECONDS` | `0.05` | Base exponential-backoff delay between retry attempts (E60-S3). |
| `LLM_PROVIDER` | `stub` | `stub`, `openai`, or `ollama`. |
| `LLM_MODEL` | empty | Global default model for the provider-neutral gateway. Empty means no global default: agents must then select their own model, or the run fails explicitly. See [Model Gateway](agents/model_gateway.md). |
| `OPENAI_API_KEY` | empty | Required when `LLM_PROVIDER=openai`. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Hosted or local model name. |
| `OPENAI_BASE_URL` | empty | Compatible gateway URL. |
| `OPENAI_TEMPERATURE` | `0.2` | LLM temperature. |
| `OPENAI_VERIFY_SSL` | `true` | TLS verification for OpenAI-compatible traffic. |
| `AUTODEV_PROJECT_ROOT` | empty | Active repository/workspace root. Also used as the default directory for `autodev.config.json` when `AUTODEV_CONFIG_PATH` is unset — the config is resolved relative to the project the service points to, not the process's launch directory. |
| `AUTODEV_CONFIG_PATH` | empty | Explicit `autodev.config.json` path, overriding the `AUTODEV_PROJECT_ROOT`-relative default. |
| `AUTODEV_CORS_ORIGINS` | local Next.js origins | Comma-separated CORS allowlist. |
| `AUTODEV_API_TOKEN` | empty | Legacy local/single-tenant compatibility PAT, mapped to `admin`. Never satisfies production readiness (ADR-018). |
| `AUTODEV_OIDC_ISSUER` | empty | Expected JWT `iss` claim; part of the OIDC/JWKS settings required for production readiness. |
| `AUTODEV_OIDC_AUDIENCE` | empty | Expected JWT `aud` claim. |
| `AUTODEV_OIDC_JWKS_URL` | empty | Provider JWKS endpoint. Must be `https://`. |
| `AUTODEV_OIDC_AUTHORIZATION_URL` | empty | Provider OIDC authorization endpoint. |
| `AUTODEV_OIDC_TOKEN_URL` | empty | Provider OIDC token endpoint. |
| `AUTODEV_OIDC_CLIENT_ID` | empty | This application's registered OIDC client id. |
| `AUTODEV_OIDC_CLIENT_SECRET` | empty | This application's registered OIDC client secret. |
| `AUTODEV_OIDC_ROLE_CLAIM` | `roles` | JWT claim carrying the caller's role(s). |
| `AUTODEV_OIDC_TENANT_CLAIM` | `tenant_id` | JWT claim carrying the caller's tenant id. |
| `AUTODEV_OIDC_SCOPE_CLAIM` | `scope` | JWT claim carrying asserted scopes narrowing the role grant. |
| `AUTODEV_OIDC_ALGORITHMS` | `RS256` | Comma-separated allowed JWS signing algorithms; never inferred from the token header. |
| `AUTODEV_OIDC_JWKS_TTL_SECONDS` | `3600` | How long a fetched JWKS key set is cached. |
| `AUTODEV_SESSION_ENCRYPTION_KEY` | empty | Key for encrypting browser session refresh tokens at rest (Fernet). Local mode uses a process-lifetime random key when unset; set explicitly in production so sessions survive a restart. |
| `AUTODEV_SESSION_TTL_SECONDS` | `28800` | Browser session lifetime (8h) before a refresh is required. |
| `AUTODEV_ENABLE_HSTS` | `false` | Emit `Strict-Transport-Security` for HTTPS deployments. |
| `AUTODEV_ENABLE_PATCH_APPLY` | `false` | Enables non-dry-run patch writes. |
| `AUTODEV_ENABLE_SANDBOX` | `false` | Enables validation command execution. |
| `AUTODEV_SANDBOX_ALLOW_LOCAL` | `false` | Allows unsandboxed local fallback. |
| `AUTODEV_SANDBOX_DOCKER_NETWORK` | `none` | Docker network mode for sandbox jobs. |
| `AUTODEV_SANDBOX_TIMEOUT_SECONDS` | `300` | Maximum wall-clock duration for one sandboxed job (1-3600s); a killed job returns code `124` (E11-S4). |
| `AUTODEV_TRUSTED_IN_PROCESS_PLUGINS` | empty | Comma-separated operator allowlist of `in-process` plugin ids permitted in production; ADR-020 (E11-S4). |
| `AUTODEV_DYNAMIC_ORCH` | `false` | Enables dynamic orchestration endpoint behavior. |
| `AUTODEV_REPO_PROVIDER` | `lexical` | Repository provider selector. |
| `AUTODEV_JOB_BACKEND` | `inprocess` | `inprocess` or `redis`. |
| `AUTODEV_REDIS_URL` | empty | Redis URL for prod queue/cache/locks. Must use `redis://` or `rediss://`. |
| `AUTODEV_JOB_RETENTION_SECONDS` | `3600` | How long a completed (done/error) job record is kept before eviction (Redis: `EXPIRE`; in-process: swept on later enqueues); `-1` disables eviction (E45-S2). |
| `AUTODEV_EVENT_BUS` | `inmemory` | Event Bus backend: `inmemory` or `redis` (Redis Streams). |
| `AUTODEV_EVENT_STREAM_MAXLEN` | `10000` | Approximate cap on retained envelopes per partition (Redis: `XADD MAXLEN ~`; in-memory: oldest-first trim); `-1` disables trimming. The durable Event Store remains the source of record (E45-S4). |
| `AUTODEV_EVENT_STORE_ENABLED` | `true` | Durably persist every published event envelope in the State Store (E8-S2). |
| `AUTODEV_EVENT_RETENTION_DAYS` | `30` | Days to retain stored events of terminal runs before compaction; `-1` keeps them forever. |
| `STORAGE_BACKEND` | `local` | `local` or `s3` artifact storage. |
| `AUTODEV_ARTIFACT_DIR` | `/data/artifacts` | Local artifact fallback directory. |
| `AUTODEV_ARTIFACT_RETENTION_DAYS` | `7` | Age guard for unreferenced-artifact GC; `-1` keeps objects forever (E8-S3). |
| `AUTODEV_MINIO_ENDPOINT` | empty | MinIO/S3 endpoint. |
| `AUTODEV_MINIO_BUCKET` | `autodev-artifacts` | Reserved legacy setting; v2 E0-S6 uses logical buckets documented in `docs/ops/storage.md`. |
| `AUTODEV_MINIO_ACCESS_KEY` | empty | MinIO/S3 access key. **Required in production**; rejected if it equals a known-default value (E11-S4). |
| `AUTODEV_MINIO_SECRET_KEY` | empty | MinIO/S3 secret key. **Required in production**; rejected if it equals a known-default value (E11-S4). |
| `AUTODEV_MINIO_SECURE` | `false` | Use TLS for MinIO/S3. |
| `AUTODEV_POSTGRES_PASSWORD` | empty | PostgreSQL password substituted into `DATABASE_URL`/Compose. **Required in production** when `DATABASE_URL` is `postgresql://`/`postgres://`; rejected if it equals a known-default value (`autodev`, `minioadmin`, `password`, `changeme`, `change-me`, case-insensitive) — E11-S4. |
| `AUTODEV_BACKUP_STATUS_PATH` | `.autodev/backup-status.json` | Durable, sanitized backup-health status file (mode `0600`); source of the `autodev_backup_*` Prometheus gauges (E11-S4). |
| `OTEL_ENABLED` | `true` | Master switch for tracing/metrics/logging export. `false` is the emergency rollback: spans, metrics, and structured logs still run in-process (no-op export), with zero Collector dependency. |
| `OTEL_SERVICE_NAME` | `autodev-backend` | OpenTelemetry service name. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | Default OTLP/HTTP collector endpoint for all three signals. |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | empty | Per-signal trace endpoint override. |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | empty | Per-signal metric endpoint override. |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | empty | Per-signal log endpoint override. |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | Trace sampler. |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | Sampling ratio argument. |
| `OTEL_METRIC_EXPORT_INTERVAL_MS` | `5000` | Periodic metric export interval. |
| `AUTODEV_OBSERVABILITY_TRACE_RETENTION` | `168h` | Tempo compactor retention for `make observability-up`. |
| `AUTODEV_OBSERVABILITY_METRIC_RETENTION` | `15d` | Prometheus `--storage.tsdb.retention.time`. |
| `AUTODEV_OBSERVABILITY_LOG_RETENTION` | `168h` | Loki `limits_config.retention_period`. |
