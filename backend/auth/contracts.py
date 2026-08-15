"""Typed contracts for Control Plane authentication and authorization.

Extended incrementally across E11-S2: Task 1 defines the role/principal core;
Task 2 adds service-credential and session records plus typed auth errors;
Task 4 adds the access-audit record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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


__all__ = [
    "AuthMethod",
    "AuthorizationRequirement",
    "PrincipalV2",
    "Role",
]
