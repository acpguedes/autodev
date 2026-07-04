# Storage Operations

E0-S6 wires Redis for ephemeral coordination and MinIO/S3-compatible storage for
artifacts while preserving a dependency-free local profile.

## Profiles

- `local`: SQLite, in-process job queue, local cache/locks, and filesystem
  artifacts under `AUTODEV_ARTIFACT_DIR`.
- `prod`: PostgreSQL, Redis queue/cache/locks, and MinIO/S3 artifact storage.
  Startup and `autodev config validate --profile prod` fail unless
  `AUTODEV_JOB_BACKEND=redis`, `AUTODEV_REDIS_URL`, `STORAGE_BACKEND=s3`, and the
  MinIO endpoint/access credentials are set.

## Redis Conventions

Redis stores only reconstructible, ephemeral data:

- `autodev:jobs:pending`: pending job IDs.
- `autodev:jobs:<job_id>`: job status/result/error hash.
- `autodev:cache:<namespace>:<key>`: cache entries with optional TTL.
- `autodev:locks:<resource>`: token-checked distributed lock leases.

Locks use `SET NX PX` for acquisition, token-checked Lua release, and
token-checked TTL renewal. Redis loss must never be the loss of durable business
state; the State Store remains authoritative.

## Artifact Conventions

Artifact object keys must be relative POSIX paths with no traversal. The logical
buckets are:

| Artifact kind | Bucket |
| --- | --- |
| Patch/diff | `patch-artifacts` |
| Validation reports | `validation-artifacts` |
| Run exports | `run-exports` |
| Logs | `logs` |

Each `put_artifact` returns `bucket`, `object_key`, `sha256`, `size_bytes`, and
`content_type` for later storage in the State Store. Local mode mirrors the same
bucket/key layout on disk so replay and recovery paths do not depend on MinIO.

## Local Production-Like Stack

Run Redis and MinIO with the production-like profile:

```bash
docker compose -f infrastructure/docker-compose.yml --profile prod up --build backend-prod
```

The profile starts PostgreSQL, Redis, MinIO, and `backend-prod`. The default
developer `backend` service remains local-first and does not require Redis or
MinIO.

## Recovery Notes

- Redis: restart and repopulate queues/cache/locks from durable state; do not
  treat Redis hashes as the system of record.
- MinIO: preserve bucket versioning and back up object data with the same RPO/RTO
  expectations as the State Store runbook in `docs/ops/backup_restore.md`.
- Local artifacts: back up `AUTODEV_ARTIFACT_DIR` together with the SQLite file
  when local replay is required.
