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
DATABASE_URL=postgresql://autodev:autodev@postgres:5432/autodev
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

`autodev config validate --profile prod` uses the same settings validation as
startup. Missing Redis/MinIO settings, `AUTODEV_JOB_BACKEND` values other than
`redis`, or `STORAGE_BACKEND` values other than `s3` abort with an actionable
error before the API starts.

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
| `LLM_PROVIDER` | `stub` | `stub`, `openai`, or `ollama`. |
| `OPENAI_API_KEY` | empty | Required when `LLM_PROVIDER=openai`. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Hosted or local model name. |
| `OPENAI_BASE_URL` | empty | Compatible gateway URL. |
| `OPENAI_TEMPERATURE` | `0.2` | LLM temperature. |
| `OPENAI_VERIFY_SSL` | `true` | TLS verification for OpenAI-compatible traffic. |
| `AUTODEV_PROJECT_ROOT` | empty | Active repository/workspace root. |
| `AUTODEV_CONFIG_PATH` | empty | Runtime UI config document path. |
| `AUTODEV_CORS_ORIGINS` | local Next.js origins | Comma-separated CORS allowlist. |
| `AUTODEV_API_TOKEN` | empty | Optional bearer token for the API. |
| `AUTODEV_ENABLE_HSTS` | `false` | Emit `Strict-Transport-Security` for HTTPS deployments. |
| `AUTODEV_ENABLE_PATCH_APPLY` | `false` | Enables non-dry-run patch writes. |
| `AUTODEV_ENABLE_SANDBOX` | `false` | Enables validation command execution. |
| `AUTODEV_SANDBOX_ALLOW_LOCAL` | `false` | Allows unsandboxed local fallback. |
| `AUTODEV_SANDBOX_DOCKER_NETWORK` | `none` | Docker network mode for sandbox jobs. |
| `AUTODEV_DYNAMIC_ORCH` | `false` | Enables dynamic orchestration endpoint behavior. |
| `AUTODEV_REPO_PROVIDER` | `lexical` | Repository provider selector. |
| `AUTODEV_JOB_BACKEND` | `inprocess` | `inprocess` or `redis`. |
| `AUTODEV_REDIS_URL` | empty | Redis URL for prod queue/cache/locks. Must use `redis://` or `rediss://`. |
| `AUTODEV_EVENT_BUS` | `inmemory` | Event Bus backend: `inmemory` or `redis` (Redis Streams). |
| `AUTODEV_EVENT_STORE_ENABLED` | `true` | Durably persist every published event envelope in the State Store (E8-S2). |
| `AUTODEV_EVENT_RETENTION_DAYS` | `30` | Days to retain stored events of terminal runs before compaction; `-1` keeps them forever. |
| `STORAGE_BACKEND` | `local` | `local` or `s3` artifact storage. |
| `AUTODEV_ARTIFACT_DIR` | `/data/artifacts` | Local artifact fallback directory. |
| `AUTODEV_ARTIFACT_RETENTION_DAYS` | `7` | Age guard for unreferenced-artifact GC; `-1` keeps objects forever (E8-S3). |
| `AUTODEV_MINIO_ENDPOINT` | empty | MinIO/S3 endpoint. |
| `AUTODEV_MINIO_BUCKET` | `autodev-artifacts` | Reserved legacy setting; v2 E0-S6 uses logical buckets documented in `docs/ops/storage.md`. |
| `AUTODEV_MINIO_ACCESS_KEY` | empty | MinIO/S3 access key. |
| `AUTODEV_MINIO_SECRET_KEY` | empty | MinIO/S3 secret key. |
| `AUTODEV_MINIO_SECURE` | `false` | Use TLS for MinIO/S3. |
| `OTEL_SERVICE_NAME` | `autodev-backend` | OpenTelemetry service name. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | OTLP collector endpoint. |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | Trace sampler. |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | Sampling ratio argument. |
