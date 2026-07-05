# Security

This document records the security posture of AutoDev Architect, the hardening
applied to the control plane and execution paths, and the environment variables
that gate sensitive behavior. It reflects a review of the backend API,
validation sandbox, patch engine, LLM client, infrastructure, CI, and frontend.

## Threat model

AutoDev is a self-hostable AI software-engineering platform. Its highest-value
assets are:

- the **LLM API key** (stored in `autodev.config.json` / environment);
- the **host filesystem** the backend can read (repository intelligence,
  symbol extraction) and write (patch engine);
- **command execution** through the validation sandbox.

The default deployment is local-first and zero-config. Anything that broadens
exposure (opening the bind address, enabling execution, disabling TLS) is
explicit opt-in via an environment variable.

## Authentication

API authentication is **opt-in** and off by default so local development stays
frictionless.

- Set `AUTODEV_API_TOKEN` to require `Authorization: Bearer <token>` on every
  request. `/health` and the OpenAPI/docs endpoints stay public so health
  checks keep working.
- Token comparison uses `hmac.compare_digest` (constant-time).
- Implemented as a global FastAPI dependency in `backend/api/security.py`, so it
  covers auto-discovered plugin routers as well as the core endpoints.

When exposing the API beyond loopback, **always** set a strong token.

## Secret handling

- `GET /config` and `PUT /config` **redact** the stored LLM API key, returning
  the placeholder `***` instead of the plaintext key. The `env_file_example`
  block is redacted the same way. (`/features` already redacted its copy.)
- When a client `PUT`s the `***` placeholder back unchanged, the previously
  stored key is preserved rather than being overwritten.
- The persisted `autodev.config.json` is written with `0600` permissions so
  other local users cannot read the key. The file is also git-ignored.
- The key is never logged.

## Filesystem confinement

- `GET /repository/symbols?path=` resolves the requested path against the
  configured project root and rejects (`403`) anything that escapes it,
  preventing arbitrary host file reads (e.g. `/etc/passwd`, `~/.ssh/*`).
- The patch engine (`backend/patches/engine.py`) already enforces the same
  `relative_to(root)` guard and is dry-run by default
  (`AUTODEV_ENABLE_PATCH_APPLY=1` to enable writes).

## Plugin permission isolation

Plugins (v2 Plugin Host, E1-S3) run under a **default-deny** permission model:

- A plugin gets no filesystem, network, subprocess, or secrets access unless its
  `plugin.yaml` manifest declares the corresponding permission and the host
  grants it.
- Host API access is **brokered** — plugins call the host through a mediated
  surface rather than reaching capabilities directly — with in-process import
  sandbox checks.
- Denied access raises a `plugin.permission.denied` audit event so attempts are
  observable.

See [`docs/plugins/permissions.md`](plugins/permissions.md) for the full model.

## Validation sandbox

Command execution is disabled unless `AUTODEV_ENABLE_SANDBOX` is set. When
enabled:

- Docker is preferred. The container now runs hardened: `--network=none`
  (override with `AUTODEV_SANDBOX_DOCKER_NETWORK`), non-root `--user`,
  `--cap-drop=ALL`, `--security-opt=no-new-privileges`, and CPU/memory/pids
  limits.
- If Docker is **not** available the runner **fails closed**. Unsandboxed host
  execution requires the explicit `AUTODEV_SANDBOX_ALLOW_LOCAL=1` opt-in.
- A command allowlist is enforced (basename of `command[0]`). Note that
  interpreters on the allowlist (`python`, `npm`) can still run arbitrary code,
  so the sandbox isolation above — not the allowlist — is the real boundary.

## Network exposure

- `sandbox/run_orchestrator.py` binds `127.0.0.1` by default with autoreload
  off. Override with `AUTODEV_HOST` / `AUTODEV_PORT` / `UVICORN_RELOAD` — only
  bind `0.0.0.0` behind a trusted proxy or with `AUTODEV_API_TOKEN` set.
- CORS origins default to the local Next.js dev server and can be overridden
  with `AUTODEV_CORS_ORIGINS` (comma-separated). Allowed methods/headers are
  restricted rather than wildcarded.

## Transport security

- `OPENAI_VERIFY_SSL=false` disables TLS verification for LLM traffic (intended
  for corporate proxies with self-signed certs). It now logs a loud warning and
  is documented as **development-only** — disabling it exposes the API key to
  man-in-the-middle attacks.
- The API emits conservative browser security headers by default:
  `Content-Security-Policy`, `Permissions-Policy`, `Referrer-Policy`,
  `X-Content-Type-Options`, and `X-Frame-Options`.
- `Strict-Transport-Security` is opt-in with `AUTODEV_ENABLE_HSTS=true`, so
  local HTTP development is not accidentally pinned to HTTPS.

## Security scanning

- `make run_secret_scanning` runs the repository secret scanner inside the
  backend container.
- The backend CI workflow runs the same scanner and a Trivy filesystem SCA gate.
  Pull requests fail on detected secrets or `CRITICAL` CVEs.
- The current baseline policy is documented in
  [`docs/security/baseline.md`](security/baseline.md).

## Container / infrastructure

- The backend image runs as a non-root user.
- `docker-compose.yml` sets `no-new-privileges`, a memory limit, and a pids
  limit on the backend service and threads `AUTODEV_API_TOKEN` through.

## Known residual risks / follow-ups

- **User-controlled LLM `base_url`**: a client that can write config can
  redirect LLM traffic (carrying the API key) to an arbitrary host. Mitigated by
  enabling `AUTODEV_API_TOKEN`; an allowlist of base URLs is a possible
  follow-up.
- **Dependency pinning**: `requirements.txt` / `pyproject.toml` use unbounded
  `>=` constraints with no lockfile. Consider pinning for reproducible,
  auditable builds.
- **Base image pinning**: container images use mutable tags
  (`python:3.11-slim`, `node:20`). Consider pinning by digest.
- **Frontend security headers**: backend headers are now set by default, but
  `next.config.mjs` still sets no frontend-specific CSP/HSTS/X-Frame headers.
