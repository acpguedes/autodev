"""Typed contracts for Control Plane authentication and authorization.

Extended incrementally across E11-S2: Task 1 defines the role/principal core;
Task 2 adds service-credential and session records plus typed auth errors;
Task 4 adds the access-audit record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal


class Role(StrEnum):
    """Canonical, emitted Control Plane roles (ADR-018 §16.1.1).

    ``author`` (the older §14.2 spelling) is never a member of this enum: it
    is accepted only as a legacy input alias for :attr:`MAINTAINER` by
    :func:`backend.auth.roles.normalize_role`.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MAINTAINER = "maintainer"
    OPERATOR = "operator"
    VIEWER = "viewer"


class AuthMethod(StrEnum):
    """How a request's principal was authenticated."""

    LOCAL = "local"
    LEGACY_PAT = "legacy_pat"
    OIDC = "oidc"
    SERVICE_KEY = "service_key"
    SESSION = "session"


@dataclass(frozen=True, slots=True)
class PrincipalV2:
    """The authenticated caller of a Control Plane request.

    Attributes:
        subject: Stable caller identifier (OIDC ``sub``, service-key subject,
            or ``"local"`` for the zero-config local principal).
        tenant_id: Tenant the caller acts within. The only authoritative
            tenant source for downstream isolation and quota decisions.
        roles: Canonical roles granted to the caller.
        scopes: Explicitly asserted scopes, if the auth method narrows the
            role grants (e.g. a service key minted with a reduced scope
            list). Empty means "no narrowing — use the full role grant".
        auth_method: How this principal was authenticated.
        credential_id: Opaque id of the presented credential (service-key
            id, session id), when applicable.
        expires_at: When this principal's credential expires, if bounded.
    """

    subject: str
    tenant_id: str
    roles: tuple[Role, ...]
    scopes: frozenset[str]
    auth_method: AuthMethod
    credential_id: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuthorizationRequirement:
    """One route's declared ``resource:action`` access policy.

    Attributes:
        scope: Required scope, e.g. ``"run:write"``.
        resource_parameter: Name of the path parameter identifying the
            resource being accessed, when the route addresses a single
            tenant-owned resource. ``None`` when the route has no such
            resource (e.g. a collection listing already tenant-scoped by the
            principal).
        conceal_cross_tenant: When ``True`` (default), a resource that exists
            but belongs to another tenant is concealed as ``404`` rather than
            revealed as ``403``.
    """

    scope: str
    resource_parameter: str | None = None
    conceal_cross_tenant: bool = True


@dataclass(frozen=True, slots=True)
class ServiceCredentialRecord:
    """A durable, hash-only record of one governed service key.

    Attributes:
        key_id: Non-secret identifier embedded in the presented key.
        tenant_id: Tenant this credential authenticates into.
        subject: Human-readable subject the credential was issued to.
        secret_hash: SHA-256 hash of the secret; the raw secret is never
            stored.
        roles: Canonical roles this credential authenticates as.
        scopes: Explicitly asserted scopes narrowing ``roles``' grants, or
            empty for the unnarrowed role grant.
        created_at: When the credential was created.
        expires_at: When the credential stops being valid (1-90 days out).
        revoked_at: When the credential was revoked, or ``None`` if active.
    """

    key_id: str
    tenant_id: str
    subject: str
    secret_hash: str
    roles: tuple[Role, ...]
    scopes: frozenset[str]
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Whether this credential is neither revoked nor expired."""
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class AuthSessionRecord:
    """A durable browser session created after an OIDC PKCE login.

    Attributes:
        session_id: Opaque session identifier (the session cookie's value).
        tenant_id: Tenant this session's principal acts within.
        subject: OIDC ``sub`` this session belongs to.
        roles: Canonical roles resolved for this session at login time.
        encrypted_refresh_token: Fernet-encrypted OIDC refresh token.
        created_at: When the session was created.
        expires_at: When the session stops being valid without a refresh.
        revoked_at: When the session was logged out, or ``None`` if active.
    """

    session_id: str
    tenant_id: str
    subject: str
    roles: tuple[Role, ...]
    encrypted_refresh_token: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Whether this session is neither revoked nor expired."""
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class AccessAuditRecord:
    """One durable, tenant-scoped access-decision audit row (Task 4).

    Never contains credentials, cookies, raw headers, request bodies, or
    prompts (ADR-018) — only stable operational identifiers.

    Attributes:
        audit_id: Opaque unique id of this audit row.
        occurred_at: When the decision was made.
        tenant_id: Tenant the decision was scoped to (``"system"`` for a
            failed-authentication row with no resolved principal).
        subject: The principal's subject (``"anonymous"`` if unauthenticated).
        auth_method: How the principal was authenticated.
        credential_id: Opaque id of the presented credential, if any.
        roles: The principal's canonical roles.
        required_scope: The route's declared required scope.
        resource_type: Stable resource-area identifier (the route's tag).
        resource_id: Path-derived resource id, if the route addresses one.
        method: HTTP method.
        route_template: The matched route's path template (never the raw
            path, which may embed identifiers).
        decision: Whether the request was allowed or denied.
        reason: Stable machine-readable reason code.
        request_id: Correlation id for cross-referencing traces/logs.
    """

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


class AuthError(Exception):
    """Base class for typed authentication/authorization failures."""


class InvalidCredentialError(AuthError):
    """A presented credential (service key, session, JWT) is not valid."""


class AuthReadinessError(RuntimeError):
    """Production startup lacks a viable authentication configuration."""


__all__ = [
    "AccessAuditRecord",
    "AuthError",
    "AuthMethod",
    "AuthReadinessError",
    "AuthSessionRecord",
    "AuthorizationRequirement",
    "InvalidCredentialError",
    "PrincipalV2",
    "Role",
    "ServiceCredentialRecord",
]
