# Security

This document records the security posture of AutoDev Architect, the hardening
applied to the control plane and execution paths, and the environment variables
that gate sensitive behavior. It reflects a review of the backend API,
validation sandbox, execution/permission engine, isolated execution
environments, secret store, quota/budget layer, patch engine, LLM client,
infrastructure, CI, and frontend. It covers the epics landed through the
v2.0 Beta wave (E11, E14, E32, E33; see
[`docs/v2_platform/progress.md`](v2_platform/progress.md) for status).

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

## Execution permission & policy engine

Every action `TaskExecutor` dispatches (E14-S1) is gated by
`PolicyService.evaluate` (`backend/execution/policy.py`, RFC-010/ADR-022:
[`docs/v2_platform/decisions/ADR-022-execution-policy-engine.md`](v2_platform/decisions/ADR-022-execution-policy-engine.md),
E14-S2) before it reaches the runner:

- Category-scoped allow/deny rules (`shell`, `fs-write`, `patch`,
  `network`, `secrets-read`, `validation`) with a durable per-decision
  audit trail and two events (`execution.policy.allowed`/`.denied`).
- Resolution mirrors `QuotaService` (ADR-019): a tenant with any stored
  rule is governed by exactly those rules; a tenant with none fails closed
  in production and falls back to a permissive default outside
  production, preserving the local-first default for unconfigured
  self-hosted instances.
- When multiple rules match, precedence is by specificity
  (dynamic-permission-with-pattern > static-with-pattern >
  dynamic-without-pattern > static-without-pattern) before effect, with
  explicit `deny` winning ties within the top tier.
- `hybrid` execution mode (E14-S3) can persist a dynamic "always allow"
  permission via `PolicyService.grant_dynamic_permission` so an
  operator-approved action class stops pausing for approval; REST:
  `GET/POST /v2/execution/policy` (`policy:read`/`policy:admin`),
  `GET/DELETE /v2/execution/policy/dynamic`.
- **PostgreSQL (E53, 2026-08-26):** `PolicyStore` runs on both SQLite and
  PostgreSQL through the E49 contract — the `prod` profile can construct
  and use it. The pending-decision terminal transition (approve/reject/
  timeout) is a single state-guarded conditional `UPDATE`
  (`WHERE ... AND status = 'pending'`), so exactly one concurrent caller
  can ever move a decision out of `pending`; `DecisionService.resolve()`
  is idempotent on a replay of the same recorded outcome but still raises
  on a replay with a *different* outcome, so a losing racer never
  silently overwrites (or appears to have gotten) the decided result. An
  unreachable store propagates its connection error rather than defaulting
  to allow (fail-closed by construction, not by an explicit catch). All
  four tables (rules, dynamic permissions, decision audit, pending
  decisions) are tenant-isolated; a decision id or task lookup meant for
  one tenant returns nothing for another.

See [`docs/execution/engine.md`](execution/engine.md) and
[`docs/execution/modes.md`](execution/modes.md) for the full execution
model this gates.

## Multi-tenant quotas and run budgets

E11-S3 (ADR-019:
[`docs/v2_platform/decisions/ADR-019-multitenant-quotas-and-run-budgets.md`](v2_platform/decisions/ADR-019-multitenant-quotas-and-run-budgets.md))
closed real cross-tenant leaks in the Control Plane — routes that had been
hardcoding a default tenant or trusting a client-supplied tenant selector
(including chat turn read/write endpoints, which had not resolved the
authenticated principal at all) now thread the E11-S2 principal's tenant
through consistently.

On top of that, a durable per-tenant quota/budget layer
(`backend/quotas/`: policy storage, concurrency leases, storage
reservations, monthly usage windows, request-rate buckets) is wired into:

- `GET/PUT /v2/quotas/usage|policy` (`quota:read`/`quota:admin`) and
  `autodev quotas get|set`;
- per-tenant storage reservation on artifact writes;
- per-credential request-rate admission in the shared `/v2` auth
  dependency;
- fail-closed concurrent-run admission in the Agent Runtime (a lease
  acquired before a run record exists, always released);
- per-run token/cost/wall-clock/step ceilings narrowed to the tenant's
  `default_run_budget` in the Reasoning Engine, with monthly usage
  recorded after each run.

Four `autodev_quota_*` OpenTelemetry gauges back a Grafana dashboard
(`infrastructure/observability/grafana/dashboards/quotas.json`).
Real per-call LLM cost/token accounting in the legacy (non-`/v2`) chat
path is out of scope for this story — see
`docs/v2_platform/phases/e11_observability_security_multitenant.md`.

## Isolated execution environments

E32 (ADR-013:
[`docs/v2_platform/decisions/ADR-013-beta-isolation-backend.md`](v2_platform/decisions/ADR-013-beta-isolation-backend.md))
adds a backend-agnostic `EnvironmentBackend` protocol
(`backend/environments/contracts.py`) around task execution, so the
sandboxing substrate can be swapped without touching callers:

- **Backend selection.** `HardenedContainerBackend`
  (`backend/environments/backends.py`, built on the existing
  `SandboxRunner`) is the Beta default. An unset or unrecognized
  `AUTODEV_EXECUTION_ENVIRONMENT_BACKEND` resolves to the fail-closed
  `UnavailableBackend` sentinel rather than a silent guess
  (`backend/environments/registry.py`).
- **Fail-closed network/filesystem policy (E32-S2,
  `backend/environments/policy.py`).** A declared network allowlist the
  Beta backend cannot mechanically enforce (only a binary default-deny is
  available; no egress proxy or DNS-level allowlist yet) denies
  provisioning outright instead of silently over- or under-granting
  access. Filesystem access under a `workspace_only` policy is checked
  against the resolved workspace mount; anything that resolves outside it
  is denied.
- **Lifecycle (E32-S3).** `EnvironmentManager`/`EnvironmentStore` provision
  one environment per dispatch batch, enforce a per-tenant concurrency
  ceiling (`AUTODEV_ENVIRONMENT_MAX_CONCURRENT`, default 8) and TTL-based
  orphan reaping (`AUTODEV_ENVIRONMENT_TTL_SECONDS`, default 1800s), and
  collect stdout/diff artifacts best-effort (a storage failure is logged
  and skipped, never fails the run).
- **Audit (E32-S4).** Four append-only events
  (`environment.instance.provisioned`, `environment.access.allowed`,
  `environment.access.denied`, `environment.instance.retired`) let an
  auditor reconstruct a run's isolation history from durable records
  alone.

Documented scope boundary (not silently narrowed): no plugin-facing
`execution_environment` extension point yet (E28), no per-profile
CPU/memory/pids override beyond the existing hardened container defaults
(E28), and workspace provisioning binds to the orchestrator's existing
`project_root` rather than a fresh ref-pinned checkout (the platform has
no VCS checkout/worktree mechanism yet; every action's filesystem access
is still checked against the workspace mount regardless). See
[`docs/environments/beta_isolation.md`](environments/beta_isolation.md)
for the full picture, including the microVM-class backend (E28, v2.2)
this abstraction is designed to accept unchanged.

## Secrets and credential governance

E33 (ADR-014:
[`docs/v2_platform/decisions/ADR-014-secret-store-format.md`](v2_platform/decisions/ADR-014-secret-store-format.md))
adds a scoped-reference secret store (`backend/secret_store/`) that never
returns a raw value over the API, injects secrets into E32 execution
environments as process environment variables without exposing them to
model context or plan/patch artifacts, redacts every resolved value from
persisted transcripts/diffs and emitted events, and supports
rotation/revocation with a full `secret.*` audit trail (including a
`secret.leak.suspected` event when an injected secret is caught in a
task's own output). See
[`docs/security/secrets.md`](security/secrets.md) for the full design and
the RBAC (`secret:use`/`secret:manage`), REST, and CLI surface.

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
- **Plugin signing / hash verification** (E13, GA, not yet started): not
  implemented. The E11-S4 trusted in-process boundary above (ADR-020)
  governs whether a plugin *may run*, not whether its bundled code has
  been tampered with.
- **Isolated execution environments beyond hardened containers** (E28,
  v2.2, not yet started): the E32 abstraction ("Isolated execution
  environments" above) is designed to accept a microVM-class backend
  (Firecracker/Kata) unchanged, but only the hardened-container backend is
  implemented today; that remains the strongest available execution
  boundary. E32 also does not yet vary per-profile CPU/memory/pids beyond
  the hardened container's existing defaults, and has no egress
  proxy/DNS-level network allowlist (binary default-deny only).
- **Secret backend beyond database-encrypted-at-rest** (deferred by
  ADR-014, not E33 scope): the Beta secret store (see "Secrets and
  credential governance" above) is envelope-encrypted in the database;
  Postgres row-level security and an external KMS/vault backend are
  deferred, not silently dropped — ADR-014 documents the trade-off.
- **Fleet-wide container digest pinning and broader SAST**: remain open
  supply-chain/E12 follow-ups; E11-S4 widens the Trivy gate (vulnerabilities
  + licenses, HIGH/CRITICAL) but does not add SAST or pin every image by
  digest.
