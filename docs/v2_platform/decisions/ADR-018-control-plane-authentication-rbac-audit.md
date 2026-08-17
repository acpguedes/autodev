# ADR-018: Control Plane Authentication, RBAC, and Access Audit

- **Status:** Accepted
- **Date:** 2026-08-15
- **Authors:** AutoDev maintainers
- **Related epic:** E11-S2
- **Supersedes/Relates to:** Supersedes the role spelling in
  `docs/architecture/v2_platform_reference.md` §14.2 with §16.1.1's roles.

## Context

The Control Plane API (`/v2` and the routers it composes) has, until now, been
protected only by an optional shared bearer token
(`backend/api/security.py`, `AUTODEV_API_TOKEN`) and a permissive placeholder
principal (`backend/api/rbac_v2.py`) that grants every caller every role.
There is no real authentication, no role hierarchy, no per-route permission
check, and no durable record of who did what. E11-S2 must add production-grade
authentication and authorization without inventing a user directory (AutoDev
delegates human identity to an external OIDC provider) and without breaking
the local, zero-config developer experience that has no external identity
provider at all.

## Decision

- **Roles.** The canonical, emitted role set is exactly `owner`, `admin`,
  `maintainer`, `operator`, and `viewer` (§16.1.1). `author` — the spelling
  used in the older §14.2 draft — is accepted only as a legacy *input* alias
  that normalizes to `maintainer`; it is never emitted or persisted. Role
  grants are maximum permissions: a caller's *effective* scopes are the
  intersection of what their role(s) grant and any narrower scope set an
  authentication method explicitly asserts (e.g. a service key minted with a
  reduced scope list). Asserted scopes can only narrow, never widen, a role's
  grants.

- **Role matrix.**

  | Capability | viewer | operator | maintainer | admin | owner |
  |---|---:|---:|---:|---:|---:|
  | Read sessions/runs/traces/catalogs/quota usage | yes | yes | yes | yes | yes |
  | Start/cancel runs and operate sessions | no | yes | yes | yes | yes |
  | Publish/edit flows, agents, skills; approve plans/patches | no | no | yes | yes | yes |
  | Install/update/remove plugins; manage config/secrets/service keys/quotas/RBAC | no | no | no | yes | yes |
  | Transfer tenant ownership | no | no | no | no | yes |

- **Identity sources.** AutoDev never stores passwords, runs MFA, or
  synchronizes a group directory. Browser users authenticate through an
  external OIDC provider (authorization-code + PKCE); AutoDev persists only a
  browser session (encrypted refresh token, HttpOnly cookie). Machine callers
  authenticate with a governed service key (`adk_live_<key-id>_<secret>`,
  stored as a salted hash only, 1–90 day expiry, immediately revocable). The
  legacy shared `AUTODEV_API_TOKEN` remains a local/single-tenant
  compatibility PAT mapped to `admin` — sufficient for a single operator's
  local install, explicitly insufficient for production readiness.

- **Local zero-config stays open.** With no OIDC settings and no active
  service credential configured, the local profile resolves every request to
  subject `local`, tenant `default`, role `owner` — unchanged behavior,
  regardless of bind address. This is a deliberate, documented trust boundary
  for local/single-user use, not a bug.

- **Production fails closed.** Production startup validates that either
  complete OIDC/JWKS settings exist or at least one active service credential
  exists in the durable Auth Store; if neither, the process refuses to start.
  A request lacking valid credentials in production gets `401`. A request
  with valid credentials lacking the required scope gets `403`. A request
  that would otherwise return `404` because a resource does not exist behaves
  identically when the resource exists but belongs to another tenant — the
  API never confirms cross-tenant existence.

- **Missing policy fails closed in production.** Every non-public route must
  declare an `AuthorizationRequirement` (one `resource:action` scope). In
  production, a matched route with no declared requirement — including one
  introduced by an auto-discovered plugin router — is denied with
  `403 authorization.policy_missing` rather than silently allowed. Local/dev
  profiles do not enforce this fail-closed default (see Consequences),
  keeping the zero-config developer loop intact.

- **Audit is mandatory, not best-effort.** Every allow/deny decision on a
  scoped route is written to a durable, tenant-scoped `access_audit` table
  before the request proceeds (allow) or is rejected (deny) is returned to
  the caller. If that durable write itself fails, an otherwise-allowed
  request is denied with `503 security.audit_unavailable` — an unauditable
  allow is treated as no different from an unauthorized one. Audit rows never
  contain credentials, cookies, raw headers, request bodies, or prompts.
  Canonical `access.request.allowed` / `access.request.denied` events are
  published best-effort after the durable write, for existing event-driven
  consumers (E11-S1 dashboards, future E32/E33 audit sinks) — they are not
  the authority.

## Alternatives considered

1. **Build a first-party user directory with passwords/MFA/SCIM** — rejected;
   AutoDev is a self-hosted engineering platform, not an identity provider,
   and every serious deployment already has an OIDC-capable IdP.
2. **Store raw service-key secrets (encrypted, not hashed) to allow secret
   recovery** — rejected; a hash-only store means a database compromise
   cannot reveal usable secrets, matching how the platform already treats
   other credentials (§18.7.5).
3. **Make audit best-effort only** — rejected; an unaudited production
   action is unacceptable for a platform whose product principle is
   auditability, so a required-audit failure denies the request instead of
   silently proceeding.
4. **Enforce the fail-closed unannotated-route policy in every profile,
   including local** — rejected for this story; it would turn any small
   local development mistake (a forgotten decorator) into a broken local dev
   loop before OIDC/service-key infrastructure is even configured. Fail-closed
   is what protects production; local capstone protection is the full test
   suite's route-coverage contract test, which runs before every merge and
   fails the build long before a real production deploy could ship an
   unannotated route.

## Consequences

- Every Control Plane router must be re-reviewed whenever a new route is
  added; the coverage contract test
  (`backend/tests/contract/test_control_plane_authorization.py`) fails CI if
  a new route ships without a declared requirement, which is the intended
  guardrail replacing runtime fail-closed-everywhere enforcement in local/dev.
- E11-S3 (multi-tenant quotas/budgets) builds directly on
  `PrincipalV2.tenant_id` as the *only* authoritative tenant source for every
  downstream isolation and quota decision; no request body, query parameter,
  or header may select a tenant.
- E11-S4 (execution security/runbooks) and E32/E33 (isolation, secrets) may
  extend the audit event catalog established here but do not change its
  durability contract.
- User provisioning, deprovisioning, MFA, and group sync remain entirely the
  operator's external OIDC provider's responsibility; AutoDev's own docs
  (`docs/security.md`) must say so explicitly to avoid operators assuming
  AutoDev manages identity lifecycle.
