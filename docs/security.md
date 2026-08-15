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
  block is redacted the same way. `/features` redacts through the same
  `Settings.redacted_model_dump()` policy — there is no second, independently
  maintained mask list to drift out of sync (E11-S4).
- When a client `PUT`s the `***` placeholder back unchanged, the previously
  stored key is preserved rather than being overwritten.
- The persisted `autodev.config.json` is written with `0600` permissions so
  other local users cannot read the key. The file is also git-ignored.
- The key is never logged.
- `DATABASE_URL` and `AUTODEV_REDIS_URL` are redacted to `***` whenever they
  embed a password; a credential-free SQLite/Redis URL stays visible for
  display. `AUTODEV_MINIO_ACCESS_KEY` and `AUTODEV_MINIO_SECRET_KEY` are
  always redacted (E11-S4).
- Production (`AUTODEV_PROFILE=prod`) rejects an empty PostgreSQL password
  and rejects known-default credentials (`autodev`, `minioadmin`, `password`,
  `changeme`, `change-me`, case-insensitive) for the PostgreSQL password and
  the MinIO access/secret keys — a fresh production deployment cannot start
  with a placeholder credential left in place (E11-S4).
  `infrastructure/docker-compose.yml`'s prod-profile backend, `postgres`, and
  `minio` services no longer bake in a fallback credential; missing
  `AUTODEV_POSTGRES_PASSWORD`/`AUTODEV_MINIO_ACCESS_KEY`/
  `AUTODEV_MINIO_SECRET_KEY` fail closed instead of silently defaulting.

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
- **Trusted-only in-process plugin boundary (ADR-020, E11-S4):** the
  permission broker above mediates *capability access*, not *process
  isolation* — an `in-process` plugin is Python code imported directly into
  the backend's own interpreter, so a narrow manifest is not by itself a
  security boundary. In production (`AUTODEV_PROFILE=prod`), an `in-process`
  plugin's id must be present in the operator allowlist
  `AUTODEV_TRUSTED_IN_PROCESS_PLUGINS`, and even a trusted `in-process`
  plugin is rejected outright if it declares `runtime.isolation` (which the
  loader cannot provide) or requests any privileged permission block
  (`network.egress`, `filesystem.read`, `filesystem.write`, `exec.commands`,
  `secrets`) — those capabilities require the `subprocess`/`wasm` loader
  instead. Local development is unaffected. See
  [`docs/v2_platform/decisions/ADR-020-trusted-in-process-plugin-boundary.md`](v2_platform/decisions/ADR-020-trusted-in-process-plugin-boundary.md).

See [`docs/plugins/permissions.md`](plugins/permissions.md) for the full model.

## Validation sandbox

Command execution is disabled unless `AUTODEV_ENABLE_SANDBOX` is set. All
sandbox decisions come from one typed, immutable `SandboxPolicy` derived from
`Settings` (`sandbox_policy_from_settings()`,
`backend/validation/sandbox.py`) rather than scattered raw `os.environ`
reads (E11-S4). When enabled:

- Docker is preferred. The container runs hardened: `--network=none`
  (override with `AUTODEV_SANDBOX_DOCKER_NETWORK`), non-root
  `--user=65534:65534`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`,
  CPU/memory/pids limits, a **read-only root filesystem** with a bounded,
  `noexec,nosuid` scratch `/tmp`, and a **read-only bind mount of only the
  resolved, guarded workspace** (never the whole host) — a job whose `cwd`
  resolves outside `AUTODEV_PROJECT_ROOT` is blocked before any process
  spawns (E11-S4).
- Every job has a bounded wall-clock timeout
  (`AUTODEV_SANDBOX_TIMEOUT_SECONDS`, default 300s); a killed job reports
  return code `124` with a sanitized timeout message (E11-S4).
- If Docker is **not** available the runner **fails closed**. Unsandboxed host
  execution requires the explicit `AUTODEV_SANDBOX_ALLOW_LOCAL=1` opt-in, and
  still runs only inside the same guarded workspace.
- A command allowlist is enforced (basename of `command[0]`). Note that
  interpreters on the allowlist (`python`, `npm`) can still run arbitrary code,
  so the sandbox isolation above — not the allowlist — is the real boundary.
- The real-Docker security contract
  (`backend/tests/integration/test_sandbox_security_contract.py`: network
  denial, workspace-only filesystem exposure, no privilege escalation) is a
  mandatory CI gate, not an optional/skippable check
  (`.github/workflows/ci-backend.yml`, `security-baseline` job).

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
  backend container, mounting the **entire working tree** read-only
  (`-v "$(CURDIR):/repo:ro"`) so newly added, not-yet-committed files are
  scanned too, not just what was last baked into the container image
  (E11-S4). The scanner itself also covers tracked *and* untracked,
  non-git-ignored files (`git ls-files --cached --others
  --exclude-standard`), not tracked files only.
- The backend CI workflow (`security-baseline` job) runs: secret scanning,
  the real-Docker sandbox security contract (see "Validation sandbox"
  above), exception-policy validation, then a Trivy filesystem scan covering
  **both vulnerabilities and licenses** at **`HIGH,CRITICAL`** severity with
  `exit-code: "1"` and `ignore-unfixed: false` — a HIGH or CRITICAL finding
  without a published fix still fails CI, it is not silently ignored
  (E11-S4, widened from a `CRITICAL`-only, `ignore-unfixed: true` vuln-only
  gate).
- Findings can only be exempted through `.trivyignore.yaml`, validated by
  `scripts/validate_security_exceptions.py` (`make
  validate_security_exceptions`) before Trivy runs. Every exception requires
  a non-empty `id`, a `statement` of the exact shape `approved-by=<identity>;
  reason=<rationale>`, and an `expires_at` date — an exception with no
  statement, a malformed statement, an unparseable or past `expires_at`, or a
  duplicate `(category, id)` pair fails validation outright. There is no
  mechanism to silently suppress a finding forever.
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
- **Plugin signing / hash verification** (E13): not implemented. The E11-S4
  trusted in-process boundary above (ADR-020) governs whether a plugin *may
  run*, not whether its bundled code has been tampered with.
- **Isolated execution environments beyond Docker** (E32): execution-environment
  profiles, backend selection, workspace lifecycle, and per-profile
  network/filesystem allowlists are not implemented. Docker with the
  hardened flags above remains the only execution boundary.
- **Secret-store abstraction** (E33): secrets remain environment-variable
  backed with redaction on exposure (this document, "Secret handling"); there
  is no encrypted secret store, scoped secret references, injection,
  rotation, or secret audit trail yet.
- **Fleet-wide container digest pinning and broader SAST**: remain open
  supply-chain/E12 follow-ups; E11-S4 widens the Trivy gate (vulnerabilities
  + licenses, HIGH/CRITICAL) but does not add SAST or pin every image by
  digest.
