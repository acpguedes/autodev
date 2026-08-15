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

## Authentication, RBAC, and access audit (Control Plane API)

The `/v2` Control Plane API (and every router under `backend/api/routers/`)
is governed by real authentication and role-based authorization (E11-S2,
ADR-018: `docs/v2_platform/decisions/ADR-018-control-plane-authentication-rbac-audit.md`).
The legacy root-relative v1 endpoints (`/plan`, `/sessions`, `/chat`, `/config`,
`/agents/contracts`, `/repository/context`, frozen at the `v1` release tag)
are unaffected — they remain public, exactly as before.

**AutoDev does not manage user identity.** There is no password store, no
user directory, no MFA, and no group synchronization. Every human identity
question — who a user is, whether their account is active, what groups they
belong to — is answered by your OIDC provider, not by AutoDev. AutoDev only
maps the identity your provider already vouches for onto its own role/scope
model.

### Local zero-config

With no OIDC settings and no active service credential configured, every
request resolves to subject `local`, tenant `default`, role `owner` —
regardless of bind address. This is a deliberate trust boundary for local,
single-operator use: don't bind a zero-config instance beyond loopback.

### Canonical roles and scopes

Five roles, strictly cumulative: `viewer` < `operator` < `maintainer` <
`admin` < `owner`. The legacy `author` spelling is accepted only as an input
alias for `maintainer`; it is never emitted or persisted. See ADR-018 for the
full capability matrix. Each role's exact `resource:action` scope grants are
defined in `backend/auth/roles.py`.

### Credential mechanisms

| Mechanism | Use | Notes |
|---|---|---|
| Legacy PAT (`AUTODEV_API_TOKEN`) | Local/single-tenant convenience | Maps to `admin`. Constant-time comparison (`hmac.compare_digest`). **Never satisfies production readiness.** |
| OIDC bearer JWT | Machine-to-machine or SPA callers holding a provider-issued token | `iss`/`aud`/`exp`/`sub`/tenant/role/scope claims and the JWKS signature are all validated; the algorithm allowlist is applied explicitly — the JWT header's own `alg` is never trusted to pick it (prevents algorithm-confusion downgrade). |
| Governed service key | CI, automation, other backends | `adk_live_<key-id>_<secret>`, created via `autodev auth service-key create`. Stored as a SHA-256 hash only — the raw secret is shown once and never recoverable. 1–90 day expiry, immediately revocable (`autodev auth service-key revoke`). |
| Browser session | Human users via the Control Center UI | External OIDC authorization-code + PKCE login (`GET /v2/auth/oidc/login`). Session id lives in an HttpOnly, Secure, `SameSite=Lax` cookie; the OIDC refresh token is encrypted at rest (Fernet) and never leaves the server. |

### Production readiness

Production startup (`AUTODEV_PROFILE=prod`) refuses to serve traffic unless
either complete OIDC/JWKS settings are configured, or at least one active
service credential already exists in the durable Auth Store
(`backend/auth/readiness.py`). The legacy PAT alone never satisfies this.

### Request outcomes

- Missing/invalid credentials: `401`.
- Valid credentials, missing required scope: `403`.
- A resource that exists but belongs to another tenant: concealed as `404`,
  identical to a genuinely unknown resource — the API never confirms
  cross-tenant existence.
- A Control Plane route (including one added by an auto-discovered plugin
  router) that ships with no declared scope: `403` in production
  (`authorization.policy_missing`). Local/dev does not enforce this
  fail-closed default — a repo-wide contract test
  (`backend/tests/contract/test_control_plane_authorization.py`) is the
  guardrail that catches an unannotated route before it ever reaches
  production.

### Access audit

Every allow/deny decision made against a resolved principal is durably
written to a tenant-scoped `access_audit` table before the caller sees the
result — an otherwise-allowed request whose audit write fails is denied
(`503 security.audit_unavailable`) rather than let through unaudited. Audit
rows never contain credentials, cookies, raw headers, request bodies, or
prompts — only stable operational identifiers (subject, roles, scope,
resource type, decision, reason). Read your own tenant's trail via
`GET /v2/audit/access` (requires `audit:read`, admin-tier).

### Implementation

- `backend/auth/` — contracts, roles, crypto, OIDC/JWKS validation, service
  lifecycle, durable persistence, audit.
- `backend/api/authorization.py` — the single global FastAPI dependency
  (`enforce_control_plane_access`) that authenticates then authorizes every
  request, covering auto-discovered plugin routers automatically.
- `backend/api/security.py` — the separate, independent legacy PAT gate,
  unchanged by E11-S2.

When exposing the API beyond loopback, configure real OIDC or a governed
service credential — do not rely on the legacy PAT.

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
