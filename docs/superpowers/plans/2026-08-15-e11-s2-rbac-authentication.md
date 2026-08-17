# E11-S2 RBAC and Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production-required authentication, the canonical five-role RBAC model, resource/action scopes, and verifiable access auditing to every Control Plane endpoint while preserving local zero-config access.

**Architecture:** A global FastAPI dependency authenticates OIDC/JWKS bearer tokens, governed service credentials, browser sessions, or the local compatibility token and stores a typed principal on the request. Each route declares one typed `resource:action` requirement; missing policy, missing scope, and mandatory-audit failure deny access in production. AutoDev delegates user identity to OIDC and persists only service-key hashes, encrypted session refresh state, and access decisions.

**Tech Stack:** FastAPI, Pydantic v2, pydantic-settings, PostgreSQL/SQLite, `PyJWT[crypto]`, `httpx`, Python `hashlib`/`hmac`/`secrets`, Next.js 14, React 18, pytest, Vitest.

**Spec:** `docs/v2_platform/phases/e11_observability_security_multitenant.md` E11-S2 and `docs/architecture/v2_platform_reference.md` §14.2, §16.1.1, §16.2, §18.7.5.

## Global Constraints

- Implement on `story/e11-s2-rbac-authentication`, cut from the E11 epic branch after E11-S1 is merged.
- Do not start GREEN implementation until the role matrix in ADR-018 is approved.
- Canonical emitted roles are exactly `owner`, `admin`, `maintainer`, `operator`, and `viewer`.
- Accept `author` only as a legacy input alias for `maintainer` when parsing existing claims or configuration; never emit or persist `author`.
- Local profile with no configured credential remains open exactly as today, regardless of bind address. It resolves to subject `local`, tenant `default`, and owner-equivalent local permissions.
- `/`, `/health`, `/v2/health`, `/docs`, `/openapi.json`, OIDC login/callback, and self-hosted docs assets remain public.
- `AUTODEV_API_TOKEN` remains a local/single-tenant compatibility PAT mapped to `admin`; it does not satisfy production readiness.
- Production startup succeeds only when complete OIDC/JWKS settings exist or at least one active governed service credential exists in the durable Auth Store.
- Validate OIDC `iss`, `aud`, `exp`, `sub`, `tenant_id`, `scope`, accepted roles, signing algorithm, and JWKS signature. JWKS URLs must use HTTPS and the validator must use the configured algorithm allowlist rather than the token header.
- Browser login uses external OIDC authorization-code plus PKCE. Do not build passwords, user enrollment, MFA, SCIM, group synchronization, or a user directory.
- Service keys use `adk_live_<key-id>_<secret>`, are stored only as hashes, expire within 90 days, and support immediate revocation.
- Browser access/refresh tokens never enter client-side JavaScript; refresh tokens are encrypted at rest.
- Missing/invalid credentials return `401`; missing permission returns `403`; concealed resource lookup returns `404`.
- Every Control Plane route, including auto-discovered plugin routers, declares a scope or an explicit public marker.
- Derive actor and tenant from the authenticated principal. Deprecated caller `actor` fields may remain parseable but are ignored.
- Mandatory access-audit failure denies an otherwise allowed production request. Audit data excludes credentials, cookies, raw headers, prompts, bodies, and secrets.
- Use PostgreSQL/SQLite durable stores already present in the repository; introduce no infrastructure service.
- Activate `.venv` for every Python, test, lint, OpenAPI, and graphify command.
- Run story-scoped checks during implementation, `make check-backend` and `make check-frontend` before story merge, and the full `make check` only at the epic-to-main PR gate.

## File Responsibility Map

Create:

- `backend/auth/contracts.py` — roles, auth methods, principal, authorization requirement, service/session/audit records, typed auth errors.
- `backend/auth/roles.py` — canonical role matrix, legacy alias normalization, effective-scope narrowing.
- `backend/auth/crypto.py` — service-key hashing/parsing and refresh-token encryption.
- `backend/auth/migrations.py` — SQLite/PostgreSQL auth tables and indexes.
- `backend/auth/store.py` — service credentials, sessions, and immutable access-audit persistence.
- `backend/auth/oidc.py` — JWKS cache, JWT validation, PKCE state, token exchange/refresh.
- `backend/auth/service.py` — request authentication and credential/session lifecycle.
- `backend/auth/audit.py` — required audit writer/query service.
- `backend/api/authorization.py` — route decorators and global enforcement.
- `backend/api/routers/auth_v2.py` — `/v2/auth/*` endpoints.
- `backend/api/routers/audit_v2.py` — `/v2/audit/access`.
- `backend/cli_plugins/auth.py` — offline service-key create/list/revoke.
- `frontend/lib/auth.ts`, `frontend/components/auth/AuthGate.tsx`, `frontend/app/auth/page.tsx` — browser session UX.
- `docs/v2_platform/decisions/ADR-018-control-plane-authentication-rbac-audit.md`.

Modify:

- `backend/requirements.txt`, `backend/config/settings.py`, `backend/api/security.py`, `backend/api/rbac_v2.py`, `backend/api/main.py`.
- Every module under `backend/api/routers/` that owns a Control Plane route.
- `backend/events/catalog.py`, `frontend/lib/api_ext.ts`, `frontend/lib/api_v2.ts`, `frontend/components/chat/useRunTimeline.ts`, `frontend/components/shell/navModel.ts`.
- `docs/api/openapi_v2.json`, `docs/security.md`, `docs/config.md`, `README.md`, `DESCRIPTION.md`, the E11 phase/progress docs, and the decisions index.

---

### Task 1: Approve ADR-018 and Add Typed RBAC Contracts

**Files:**

- Create: `docs/v2_platform/decisions/ADR-018-control-plane-authentication-rbac-audit.md`
- Create: `backend/auth/__init__.py`
- Create: `backend/auth/contracts.py`
- Create: `backend/auth/roles.py`
- Create: `backend/tests/unit/auth/test_roles.py`
- Modify: `docs/v2_platform/decisions/README.md`

**Interfaces:**

```python
class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MAINTAINER = "maintainer"
    OPERATOR = "operator"
    VIEWER = "viewer"


class AuthMethod(StrEnum):
    LOCAL = "local"
    LEGACY_PAT = "legacy_pat"
    OIDC = "oidc"
    SERVICE_KEY = "service_key"
    SESSION = "session"


@dataclass(frozen=True, slots=True)
class PrincipalV2:
    subject: str
    tenant_id: str
    roles: tuple[Role, ...]
    scopes: frozenset[str]
    auth_method: AuthMethod
    credential_id: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuthorizationRequirement:
    scope: str
    resource_parameter: str | None = None
    conceal_cross_tenant: bool = True
```

- Produces: `normalize_role(value: str) -> Role`, `normalize_scopes(value: str | Sequence[str]) -> frozenset[str]`, and `effective_scopes(roles: tuple[Role, ...], asserted_scopes: frozenset[str] | None) -> frozenset[str]`.

- [ ] **Step 1: Write the RED role tests**

```python
def test_author_is_only_an_input_alias() -> None:
    assert normalize_role("author") is Role.MAINTAINER
    assert normalize_role("maintainer") is Role.MAINTAINER


def test_author_is_never_emitted() -> None:
    principal = PrincipalV2(
        subject="user-1",
        tenant_id="tenant-a",
        roles=(normalize_role("author"),),
        scopes=frozenset({"flow:write"}),
        auth_method=AuthMethod.OIDC,
    )
    assert [role.value for role in principal.roles] == ["maintainer"]


def test_asserted_scopes_only_narrow_role_grants() -> None:
    result = effective_scopes(
        (Role.MAINTAINER,),
        frozenset({"run:read", "flow:write", "plugin:admin"}),
    )
    assert result == frozenset({"run:read", "flow:write"})
```

- [ ] **Step 2: Run RED verification**

Run:

```bash
source .venv/bin/activate && pytest backend/tests/unit/auth/test_roles.py -q
```

Expected: collection fails because `backend.auth` does not exist.

- [ ] **Step 3: Draft and approve ADR-018**

ADR-018 records that §16.1.1 supersedes §14.2’s older role spelling, `maintainer` is canonical, `author` is ingestion-only compatibility, role grants are maximum permissions, asserted scopes only narrow grants, OIDC owns user identity, and missing policy/audit fails closed in production. It includes the exact matrix:

| Capability | viewer | operator | maintainer | admin | owner |
|---|---:|---:|---:|---:|---:|
| Read sessions/runs/traces/catalogs/quota usage | yes | yes | yes | yes | yes |
| Start/cancel runs and operate sessions | no | yes | yes | yes | yes |
| Publish/edit flows, agents, skills; approve plans/patches | no | no | yes | yes | yes |
| Install/update/remove plugins; manage config/secrets/service keys/quotas/RBAC | no | no | no | yes | yes |
| Transfer tenant ownership | no | no | no | no | yes |

Do not proceed to Step 4 until ADR-018 status is `Accepted`.

- [ ] **Step 4: Implement the minimal role/scope model**

Define immutable cumulative grants using `resource:action` strings. At minimum include `session:read|write`, `run:read|write|cancel`, `flow:read|write|execute`, `agent:read|write|invoke`, `skill:read|write|invoke`, `plan:read|write|approve`, `patch:propose|review|apply`, `plugin:read|admin`, `config:read_redacted|write_safe|admin`, `mcp:invoke`, `quota:read|admin`, `audit:read`, `service_credential:admin`, `rbac:admin`, and `tenant:owner`. Reject unknown roles/scopes and scope strings outside `^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$`.

- [ ] **Step 5: Run GREEN verification and commit**

```bash
source .venv/bin/activate && pytest backend/tests/unit/auth/test_roles.py -q
```

Expected: alias, emitted-role, hierarchy, and scope-narrowing tests pass.

```bash
git add backend/auth/__init__.py backend/auth/contracts.py backend/auth/roles.py backend/tests/unit/auth/test_roles.py docs/v2_platform/decisions/ADR-018-control-plane-authentication-rbac-audit.md docs/v2_platform/decisions/README.md
git commit -m "feat(e11): define canonical RBAC contracts"
```

---

### Task 2: Add Governed Authentication, Sessions, and Production Readiness

**Files:**

- Create: `backend/auth/crypto.py`
- Create: `backend/auth/migrations.py`
- Create: `backend/auth/store.py`
- Create: `backend/auth/oidc.py`
- Create: `backend/auth/service.py`
- Create: `backend/auth/readiness.py`
- Create: `backend/api/routers/auth_v2.py`
- Create: `backend/cli_plugins/auth.py`
- Create: `backend/tests/unit/auth/test_auth_store.py`
- Create: `backend/tests/unit/auth/test_oidc.py`
- Create: `backend/tests/integration/test_auth_api.py`
- Create: `backend/tests/unit/cli_plugins/test_auth_cli.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/config/settings.py`
- Modify: `backend/api/main.py`

**Interfaces:**

```python
def validate_auth_readiness(
    settings: Settings,
    store: AuthStore,
    *,
    now: datetime | None = None,
) -> None


class AuthService:
    async def authenticate_request(self, request: Request) -> PrincipalV2
    def create_service_key(
        self,
        *,
        tenant_id: str,
        subject: str,
        roles: tuple[Role, ...],
        scopes: frozenset[str],
        expires_at: datetime,
    ) -> tuple[ServiceCredentialRecord, str]
    def revoke_service_key(self, *, tenant_id: str, key_id: str) -> bool
    def authenticate_session(self, presented: str) -> PrincipalV2
```

`AuthStore` persists `service_credentials`, `auth_sessions`, and `access_audit` through a namespaced SQLite/PostgreSQL migration list. Credential/session lookup is internal by opaque ID; all list/revoke/audit operations require explicit tenant predicates.

- [ ] **Step 1: Write RED authentication/readiness tests**

```python
def test_local_zero_config_remains_open() -> None:
    principal = auth_service(local_settings()).authenticate_local_request()
    assert principal.tenant_id == "default"
    assert principal.roles == (Role.OWNER,)


def test_production_without_oidc_or_service_key_fails() -> None:
    with pytest.raises(RuntimeError, match="OIDC/JWKS or an active service credential"):
        validate_auth_readiness(prod_settings(), empty_auth_store())


def test_legacy_pat_does_not_satisfy_production() -> None:
    settings = prod_settings(autodev_api_token="legacy")
    with pytest.raises(RuntimeError):
        validate_auth_readiness(settings, empty_auth_store())


def test_service_key_is_hash_only_and_revocable(tmp_path: Path) -> None:
    service = auth_service_for(tmp_path)
    record, secret = service.create_service_key(
        tenant_id="tenant-a",
        subject="ci",
        roles=(Role.OPERATOR,),
        scopes=frozenset({"run:read", "run:write"}),
        expires_at=utcnow() + timedelta(days=30),
    )
    assert secret.startswith(f"adk_live_{record.key_id}_")
    assert secret not in sqlite_text(tmp_path / "auth.db")
    service.revoke_service_key(tenant_id="tenant-a", key_id=record.key_id)
    with pytest.raises(InvalidCredentialError):
        service.authenticate_service_key(secret)
```

Add JWT tests for valid claims, unknown `kid`, invalid signature, wrong issuer/audience, expiry, missing tenant/scope/role, and `author` normalization. Add PKCE tests asserting secure HttpOnly session cookies and encrypted refresh persistence.

- [ ] **Step 2: Run RED verification**

```bash
source .venv/bin/activate && pytest backend/tests/unit/auth/test_auth_store.py backend/tests/unit/auth/test_oidc.py backend/tests/integration/test_auth_api.py backend/tests/unit/cli_plugins/test_auth_cli.py -q
```

Expected: authentication modules, migrations, endpoints, and CLI are absent.

- [ ] **Step 3: Implement minimal auth persistence and configuration**

Add `PyJWT[crypto]>=2.13.0,<3`; this security floor includes the upstream JWK/JWKS fixes current on 2026-08-15. Do not pin `cryptography` independently. Add issuer, audience, HTTPS-only JWKS URL, authorization URL, token URL, client ID, configurable role/tenant/scope claim names, signing-algorithm allowlist, JWKS TTL, encrypted-session key, and session TTL settings. Keep local defaults empty/open. Reject any algorithm inferred solely from the JWT header.

Service credentials use `hashlib.sha256` over high-entropy secrets and `hmac.compare_digest`; require expiry from 1 through 90 days and scopes contained by the role grants. Encrypt refresh tokens with `Fernet`. Add offline commands:

```text
autodev auth service-key create --tenant-id TENANT --subject SUBJECT --role ROLE --scope SCOPE --expires-in-days N
autodev auth service-key list --tenant-id TENANT
autodev auth service-key revoke --tenant-id TENANT --key-id KEY_ID
```

Create prints the secret once; list never returns a secret or hash.

- [ ] **Step 4: Implement OIDC/JWKS and session endpoints**

Validate JWTs with the configured issuer, audience, algorithm allowlist, and JWKS key. Cache JWKS for the configured TTL and refresh once for an unknown `kid`. Implement S256 PKCE and these endpoints:

```text
GET    /v2/auth/oidc/login?returnTo=/relative-path
GET    /v2/auth/oidc/callback?code=...&state=...
GET    /v2/auth/me
POST   /v2/auth/session/refresh
DELETE /v2/auth/session
GET    /v2/auth/service-credentials
POST   /v2/auth/service-credentials
DELETE /v2/auth/service-credentials/{key_id}
```

OIDC login/callback are public. Service-key management derives the current tenant and requires `service_credential:admin`. Production lifespan calls `validate_auth_readiness()` after Auth Store migration and before accepting traffic.

- [ ] **Step 5: Run GREEN verification and commit**

```bash
source .venv/bin/activate && pytest backend/tests/unit/auth/test_auth_store.py backend/tests/unit/auth/test_oidc.py backend/tests/integration/test_auth_api.py backend/tests/unit/cli_plugins/test_auth_cli.py -q
```

Expected: local compatibility, production readiness, hash-only keys, 90-day expiry, revocation, strict JWT validation, PKCE, session rotation, and one-time secret response pass.

```bash
git add backend/requirements.txt backend/config/settings.py backend/auth backend/api/routers/auth_v2.py backend/api/main.py backend/cli_plugins/auth.py backend/tests/unit/auth backend/tests/integration/test_auth_api.py backend/tests/unit/cli_plugins/test_auth_cli.py
git commit -m "feat(e11): add governed authentication and sessions"
```

---

### Task 3: Enforce Typed Route Policies and Trusted Resource Context

**Files:**

- Create: `backend/api/authorization.py`
- Create: `backend/tests/unit/api/test_rbac_v2.py`
- Create: `backend/tests/contract/test_control_plane_authorization.py`
- Modify: `backend/api/security.py`
- Modify: `backend/api/rbac_v2.py`
- Modify: `backend/api/main.py`
- Modify: all route-owning modules under `backend/api/routers/`
- Modify: `backend/api/routers/plan_approval_v2_models.py`
- Modify: `backend/api/routers/patches_review_v2_models.py`
- Modify: affected API tests.

**Interfaces:**

```python
def requires_scope(
    scope: str,
    *,
    resource_parameter: str | None = None,
    conceal_cross_tenant: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]


def public_endpoint(endpoint: Callable[..., Any]) -> Callable[..., Any]


async def enforce_control_plane_access(request: Request) -> None


def require_v2_principal(request: Request) -> PrincipalV2
```

- [ ] **Step 1: Write RED enforcement/coverage tests**

```python
def test_viewer_cannot_create_session(client: TestClient) -> None:
    response = client.post(
        "/v2/sessions",
        headers=bearer_header(viewer_token()),
        json={"goal": "change code"},
    )
    assert response.status_code == 403


def test_unannotated_dynamic_route_fails_closed_in_production() -> None:
    response = TestClient(prod_app_with_unannotated_route()).get(
        "/v2/plugin-route",
        headers=bearer_header(viewer_token()),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "authorization.policy_missing"


def test_every_non_public_route_declares_policy() -> None:
    missing = protected_routes_without_requirement(app)
    assert missing == []
```

Add negative tests proving a caller-supplied plan/flow actor is ignored and a protected resource path cannot select another tenant.

- [ ] **Step 2: Run RED verification**

```bash
source .venv/bin/activate && pytest backend/tests/unit/api/test_rbac_v2.py backend/tests/contract/test_control_plane_authorization.py backend/tests/unit/api/test_api_security.py -q
```

Expected: the current permissive principal grants all access and coverage reports unannotated routes.

- [ ] **Step 3: Implement one global authentication/authorization dependency**

Authentication order is public marker, service key, local compatibility PAT, OIDC bearer JWT, session cookie, local zero-config principal, then `401`. Store the principal in `request.state.principal`. Read `AuthorizationRequirement` from the matched endpoint. In production, missing metadata returns `403 authorization.policy_missing`; missing scope returns `403 authorization.scope_missing`.

`backend/api/rbac_v2.py` re-exports `PrincipalV2` and returns the request-state principal so existing router dependency signatures remain stable.

- [ ] **Step 4: Annotate every route using the ADR-018 matrix**

Use this exact mapping:

| Area | Read | Mutate |
|---|---|---|
| sessions/chat/orchestration/runs stream | `session:read`, `run:read` | `session:write`, `run:write`, `run:cancel` |
| flows | `flow:read` | `flow:write`, `flow:execute` |
| agents/skills | `agent:read`, `skill:read` | `agent:write|invoke`, `skill:write|invoke` |
| plans/patches | `plan:read`, `run:read` | `plan:write|approve`, `patch:propose|review|apply` |
| plugins/extensions | `plugin:read` | `plugin:admin` |
| config/provider/features | `config:read_redacted` | `config:write_safe`, `config:admin` |
| context/repository/evals/routing/metrics | matching read scope | `flow:execute` for governed execution |
| MCP | none | `mcp:invoke` |
| jobs/validation | `run:read` | `run:write` |
| auth/audit/quotas | current-principal read | `service_credential:admin`, `audit:read`, `quota:admin` |

Keep deprecated `actor` fields parseable but always pass `principal.subject` to plan, flow, and patch state transitions.

- [ ] **Step 5: Run GREEN verification and commit**

```bash
source .venv/bin/activate && pytest backend/tests/unit/api/test_rbac_v2.py backend/tests/contract/test_control_plane_authorization.py backend/tests/unit/api/test_api_security.py backend/tests/unit/plans/test_plans_api.py backend/tests/unit/patches/test_patches_api.py backend/tests/unit/flows/test_flows_api.py -q
```

Expected: public/local compatibility, 401/403 behavior, full route coverage, plugin-router fail-closed behavior, role negatives, and trusted actor tests pass.

```bash
git add backend/api/authorization.py backend/api/security.py backend/api/rbac_v2.py backend/api/main.py backend/api/routers backend/tests/unit/api backend/tests/contract/test_control_plane_authorization.py backend/tests/unit/plans backend/tests/unit/patches backend/tests/unit/flows
git commit -m "feat(e11): enforce Control Plane RBAC"
```

---

### Task 4: Persist Access and Denial Audit

**Files:**

- Create: `backend/auth/audit.py`
- Create: `backend/api/routers/audit_v2.py`
- Create: `backend/tests/unit/auth/test_audit.py`
- Modify: `backend/auth/contracts.py`
- Modify: `backend/auth/store.py`
- Modify: `backend/api/authorization.py`
- Modify: `backend/events/catalog.py`
- Modify: `backend/tests/unit/events/test_event_store.py`
- Modify: `backend/tests/integration/test_auth_api.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class AccessAuditRecord:
    audit_id: str
    occurred_at: datetime
    tenant_id: str
    subject: str
    auth_method: AuthMethod
    credential_id: str | None
    roles: tuple[Role, ...]
    required_scope: str
    resource_type: str
    resource_id: str | None
    method: str
    route_template: str
    decision: Literal["allowed", "denied"]
    reason: str
    request_id: str


class AuditWriter:
    def record(self, record: AccessAuditRecord, *, required: bool) -> None
    def list(
        self,
        *,
        tenant_id: str,
        limit: int,
        before: datetime | None,
    ) -> list[AccessAuditRecord]
```

- [ ] **Step 1: Write RED audit tests**

```python
def test_allowed_and_denied_decisions_are_durable(client: TestClient, store: AuthStore) -> None:
    assert client.get("/v2/sessions", headers=bearer_header(viewer_token())).status_code == 200
    assert client.post(
        "/v2/sessions",
        headers=bearer_header(viewer_token()),
        json={"goal": "x"},
    ).status_code == 403
    decisions = [item.decision for item in store.list_access_audit(
        tenant_id="tenant-a", limit=10, before=None
    )]
    assert decisions == ["denied", "allowed"]


def test_required_audit_failure_blocks_allowed_request(client: TestClient) -> None:
    override_audit_writer(FailingAuditWriter())
    response = client.get("/v2/sessions", headers=bearer_header(viewer_token()))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "security.audit_unavailable"
```

Add a test that serializes audit rows/events and asserts a presented bearer secret, cookie, body text, and configuration secret are absent.

- [ ] **Step 2: Run RED verification**

```bash
source .venv/bin/activate && pytest backend/tests/unit/auth/test_audit.py backend/tests/integration/test_auth_api.py backend/tests/unit/events/test_event_store.py -q
```

Expected: access decisions are not persisted and audit failure does not deny.

- [ ] **Step 3: Implement authoritative audit rows plus integration events**

Write `access_audit` before allowing an authorized operation. A required append failure returns `503 security.audit_unavailable`. An already-denied request remains denied if audit persistence fails and emits a critical redacted log.

After durable append, publish best-effort canonical events `access.request.allowed` and `access.request.denied`. Payload fields are subject ID, auth method, credential ID, canonical roles, required scope, resource type/ID, method, route template, decision, reason, and request ID. Authentication failures use tenant `system`, subject `anonymous`, and no presented-token data.

- [ ] **Step 4: Add tenant-scoped audit retrieval**

Implement `GET /v2/audit/access?limit=50&before=<timestamp>`, require `audit:read`, restrict to `principal.tenant_id`, and cap `limit` at 200.

- [ ] **Step 5: Run GREEN verification and commit**

```bash
source .venv/bin/activate && pytest backend/tests/unit/auth/test_audit.py backend/tests/integration/test_auth_api.py backend/tests/unit/events/test_event_store.py -q
```

Expected: allowed/denied rows, redaction, mandatory failure, event validation, and tenant-scoped retrieval pass.

```bash
git add backend/auth/contracts.py backend/auth/store.py backend/auth/audit.py backend/api/authorization.py backend/api/routers/audit_v2.py backend/events/catalog.py backend/tests/unit/auth/test_audit.py backend/tests/integration/test_auth_api.py backend/tests/unit/events/test_event_store.py
git commit -m "feat(e11): persist access and denial audit"
```

---

### Task 5: Wire Browser Credentials and Publish the API Contract

**Files:**

- Create: `frontend/lib/auth.ts`
- Create: `frontend/components/auth/AuthGate.tsx`
- Create: `frontend/app/auth/page.tsx`
- Create: `frontend/lib/__tests__/auth.test.ts`
- Create: `frontend/components/auth/__tests__/AuthGate.test.tsx`
- Create: `frontend/e2e/auth-session.spec.ts`
- Modify: `frontend/lib/api_ext.ts`
- Modify: `frontend/lib/api_v2.ts`
- Modify: `frontend/components/chat/useRunTimeline.ts`
- Modify: `frontend/components/shell/navModel.ts`
- Modify: `backend/tests/integration/test_v2_api_contract.py`
- Modify: `scripts/generate_openapi_v2.py`
- Modify: `docs/api/openapi_v2.json`

**Interfaces:**

```typescript
export type AuthPrincipalV2 = {
  subject: string;
  tenantId: string;
  roles: Array<"owner" | "admin" | "maintainer" | "operator" | "viewer">;
  scopes: string[];
  authMethod: "local" | "legacy_pat" | "oidc" | "service_key" | "session";
};

export async function getCurrentPrincipal(): Promise<AuthPrincipalV2 | null>;
export function oidcLoginUrl(returnTo: string): string;
export async function logoutSession(): Promise<void>;
```

- [ ] **Step 1: Write RED frontend/OpenAPI tests**

```typescript
it("sends browser credentials on JSON requests", async () => {
  mockJsonResponse({ subject: "u", tenantId: "t", roles: ["viewer"], scopes: [], authMethod: "session" });
  await getCurrentPrincipal();
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/v2/auth/me"),
    expect.objectContaining({ credentials: "include" })
  );
});
```

```python
def test_every_protected_openapi_operation_publishes_scope() -> None:
    assert protected_operations_without_scope(app.openapi()) == []


def test_openapi_emits_only_canonical_roles() -> None:
    role_enum = app.openapi()["components"]["schemas"]["Role"]["enum"]
    assert role_enum == ["owner", "admin", "maintainer", "operator", "viewer"]
```

- [ ] **Step 2: Run RED verification**

```bash
cd frontend && npm test -- lib/__tests__/auth.test.ts components/auth/__tests__/AuthGate.test.tsx
```

Expected: auth client/gate are missing and fetch omits credentials.

```bash
source .venv/bin/activate && pytest backend/tests/integration/test_v2_api_contract.py -q
```

Expected: security schemes and per-operation scope extensions are absent.

- [ ] **Step 3: Implement browser session UX**

Set `credentials: "include"` on JSON and SSE fetches. `AuthGate` loads `/v2/auth/me`, leaves local zero-config transparent, links production `401` to OIDC login, displays subject/tenant/canonical roles, and posts logout. Never accept or store a service key in browser state.

- [ ] **Step 4: Generate auth-aware OpenAPI**

Publish `oidcBearer`, `serviceBearer`, and `sessionCookie` security schemes. Derive `x-autodev-required-scope` from each endpoint’s `AuthorizationRequirement`; do not maintain a second scope registry.

```bash
source .venv/bin/activate && python scripts/generate_openapi_v2.py
```

Expected: the generated document contains auth/audit endpoints, canonical role schemas, security alternatives, and required scopes.

- [ ] **Step 5: Run GREEN verification and commit**

```bash
cd frontend && npm test -- lib/__tests__/auth.test.ts components/auth/__tests__/AuthGate.test.tsx
```

```bash
cd frontend && npm run e2e -- auth-session.spec.ts
```

```bash
source .venv/bin/activate && pytest backend/tests/integration/test_v2_api_contract.py backend/tests/contract/test_control_plane_authorization.py -q
```

Expected: session UX, credential transport, canonical roles, and OpenAPI authorization metadata pass.

```bash
git add frontend/lib/auth.ts frontend/lib/api_ext.ts frontend/lib/api_v2.ts frontend/components/auth/AuthGate.tsx frontend/app/auth/page.tsx frontend/components/chat/useRunTimeline.ts frontend/components/shell/navModel.ts frontend/lib/__tests__/auth.test.ts frontend/components/auth/__tests__/AuthGate.test.tsx frontend/e2e/auth-session.spec.ts scripts/generate_openapi_v2.py docs/api/openapi_v2.json backend/tests/integration/test_v2_api_contract.py
git commit -m "feat(e11): connect Control Center authentication"
```

---

### Task 6: Document and Verify E11-S2

**Files:**

- Modify: `docs/security.md`
- Modify: `docs/config.md`
- Modify: `README.md`
- Modify: `DESCRIPTION.md`
- Modify: `docs/v2_platform/phases/e11_observability_security_multitenant.md`
- Modify: `docs/v2_platform/progress.md`

**Interfaces:** None; this task verifies and publishes the implemented contracts.

- [ ] **Step 1: Write the operator-facing documentation**

Document local zero-config behavior, compatibility PAT behavior, production readiness, OIDC/JWKS settings/claims, PKCE sessions, offline service-key commands, 90-day expiry, immediate revocation, the exact role/scope matrix, `author` input alias behavior, 401/403/404 semantics, audit durability/redaction, and bootstrap order. Explicitly state that user directory, password, MFA, and SCIM functions remain external to AutoDev.

- [ ] **Step 2: Correct trackers only after DoD evidence exists**

Correct the E11 phase’s stale “starts from zero” statement. Mark E11-S2 complete only after negative authorization tests, verifiable audit tests, generated OpenAPI, frontend authentication, and documentation are present.

- [ ] **Step 3: Run consolidated story checks**

```bash
source .venv/bin/activate && pytest backend/tests/unit/auth backend/tests/unit/api/test_api_security.py backend/tests/unit/api/test_rbac_v2.py backend/tests/contract/test_control_plane_authorization.py backend/tests/integration/test_auth_api.py backend/tests/integration/test_v2_api_contract.py -q
```

Expected: all S2 behavior tests pass.

```bash
source .venv/bin/activate && make check-backend
```

Expected: backend lint, mypy, tests, and coverage pass.

```bash
source .venv/bin/activate && make check-frontend
```

Expected: frontend lint, typecheck, tests, and build pass.

```bash
source .venv/bin/activate && graphify update .
```

Expected: graph update completes without extraction errors.

- [ ] **Step 4: Commit docs and tracker state**

```bash
git add docs/security.md docs/config.md README.md DESCRIPTION.md docs/v2_platform/phases/e11_observability_security_multitenant.md docs/v2_platform/progress.md graphify-out
git commit -m "docs(e11): publish RBAC and authentication operations"
```

## Self-Review

- S2-T1 is covered by Tasks 1 and 3.
- S2-T2 is covered by Tasks 2, 3, and 5.
- S2-T3 is covered by Task 4.
- The primary role matrix is `owner/admin/maintainer/operator/viewer`; `author` is ingestion-only compatibility.
- Local zero-config access remains open without a bind-address restriction.
- Production requires OIDC/JWKS or an active governed service credential.
- Every dynamic/static Control Plane route is covered by an executable policy contract test.
- Service credentials are hash-only, short-lived, tenant-scoped, and revocable.
- Browser sessions use external OIDC rather than an AutoDev user directory.
- Audit persistence is authoritative and secret-redacted.
- Public API, backend, frontend, docs, ADR, and tracker changes all have explicit owners and checks.
- Interface names/types are consistent across tasks.
- No unresolved implementation marker or unspecified error-handling instruction remains.
