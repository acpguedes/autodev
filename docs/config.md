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
```

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
| `AUTODEV_REDIS_URL` | empty | Redis URL for prod queues/locks. |
| `STORAGE_BACKEND` | `local` | `local` or `s3` artifact storage. |
| `AUTODEV_ARTIFACT_DIR` | `/data/artifacts` | Local artifact fallback directory. |
| `AUTODEV_MINIO_ENDPOINT` | empty | MinIO/S3 endpoint. |
| `AUTODEV_MINIO_BUCKET` | `autodev-artifacts` | Artifact bucket. |
| `AUTODEV_MINIO_ACCESS_KEY` | empty | MinIO/S3 access key. |
| `AUTODEV_MINIO_SECRET_KEY` | empty | MinIO/S3 secret key. |
| `AUTODEV_MINIO_SECURE` | `false` | Use TLS for MinIO/S3. |
| `OTEL_SERVICE_NAME` | `autodev-backend` | OpenTelemetry service name. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | OTLP collector endpoint. |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | Trace sampler. |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | Sampling ratio argument. |
