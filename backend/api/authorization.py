"""Global Control Plane authentication + authorization enforcement (E11-S2 Task 3).

Every ``/v2`` (and Control Plane router-owned) route must declare either
``@public_endpoint`` or ``@requires_scope(...)``. :func:`enforce_control_plane_access`
is installed as a single app-level FastAPI dependency
(:data:`backend.api.main.app`'s ``dependencies=``) so it runs before every
matched route, including routes contributed by auto-discovered plugin
routers that know nothing about this module.

The legacy v1 endpoints defined directly in :mod:`backend.api.main` are
frozen (CLAUDE.md) and out of scope for this coverage contract; they are
identified structurally (by their endpoint's ``__module__``), not by an
easily-stale path list.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TypeVar

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute

from backend.auth.audit import get_audit_writer, new_audit_id, publish_access_event
from backend.auth.contracts import (
    AccessAuditRecord,
    AuthorizationRequirement,
    InvalidCredentialError,
    PrincipalV2,
)
from backend.auth.roles import effective_scopes
from backend.auth.service import get_auth_service
from backend.auth.store import utcnow
from backend.config.settings import Settings

F = TypeVar("F", bound=Callable[..., Any])

_REQUIREMENT_ATTR = "__autodev_auth_requirement__"
_PUBLIC_ATTR = "__autodev_auth_public__"

# Frozen v1 surface (backend/api/main.py) and framework-internal routes
# (OpenAPI schema, docs) are out of the E11-S2 Control Plane coverage
# contract. Identified by module rather than path, so an accidental path
# collision with a real v2 route can never silently exempt it.
_EXCLUDED_MODULE_PREFIXES = ("backend.api.main", "fastapi.", "starlette.")


def requires_scope(
    scope: str,
    *,
    resource_parameter: str | None = None,
    conceal_cross_tenant: bool = True,
) -> Callable[[F], F]:
    """Declare one route's required ``resource:action`` authorization scope.

    Args:
        scope: The required scope, e.g. ``"run:write"``.
        resource_parameter: Name of the path parameter identifying a single
            tenant-owned resource this route addresses, if any. Reserved for
            E11-S3's tenant-scoped resource lookups; currently recorded but
            not yet enforced (no domain object carries a ``tenant_id`` to
            compare against before E11-S3 lands).
        conceal_cross_tenant: Whether a cross-tenant resource should be
            concealed as ``404`` rather than revealed as ``403``. Reserved
            alongside ``resource_parameter``.

    Returns:
        A decorator that attaches the requirement to the endpoint function
        without wrapping it (preserving FastAPI's signature introspection).
    """
    requirement = AuthorizationRequirement(
        scope=scope,
        resource_parameter=resource_parameter,
        conceal_cross_tenant=conceal_cross_tenant,
    )

    def decorator(endpoint: F) -> F:
        setattr(endpoint, _REQUIREMENT_ATTR, requirement)
        return endpoint

    return decorator


def public_endpoint(endpoint: F) -> F:
    """Mark a route as reachable without authentication or authorization.

    Args:
        endpoint: The route handler function.

    Returns:
        ``endpoint``, unchanged aside from the attached marker.
    """
    setattr(endpoint, _PUBLIC_ATTR, True)
    return endpoint


def get_authorization_requirement(endpoint: Any) -> AuthorizationRequirement | None:
    """Read a route's declared requirement, if any.

    Args:
        endpoint: The matched route's handler function.

    Returns:
        The declared :class:`AuthorizationRequirement`, or ``None``.
    """
    return getattr(endpoint, _REQUIREMENT_ATTR, None)


def is_public_endpoint(endpoint: Any) -> bool:
    """Whether a route is marked public via :func:`public_endpoint`.

    Args:
        endpoint: The matched route's handler function.

    Returns:
        ``True`` if the route was decorated with :func:`public_endpoint`.
    """
    return bool(getattr(endpoint, _PUBLIC_ATTR, False))


def iter_api_routes(routes: Iterable[Any]) -> Iterator[APIRoute]:
    """Recursively flatten every :class:`APIRoute`, including nested routers.

    FastAPI represents an ``include_router()``-registered sub-router as a
    wrapper object rather than inlining its routes into the parent's
    ``routes`` list, so a naive ``isinstance`` filter over ``app.routes``
    misses everything registered through :func:`backend.api.routers.include_all_routers`.

    Args:
        routes: An iterable of Starlette/FastAPI route (or route-container)
            objects, typically ``app.routes``.

    Yields:
        Every concrete :class:`APIRoute` reachable from ``routes``.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from iter_api_routes(route.original_router.routes)
        elif hasattr(route, "routes"):
            yield from iter_api_routes(route.routes)


def _is_excluded(endpoint: Any) -> bool:
    """Whether an endpoint belongs to the frozen v1 surface or the framework."""
    module = getattr(endpoint, "__module__", "") or ""
    return any(module.startswith(prefix) for prefix in _EXCLUDED_MODULE_PREFIXES)


def protected_routes_without_requirement(app: Any) -> list[str]:
    """List every non-public, in-scope route missing a declared requirement.

    This is the enforcement mechanism's coverage contract: it is what
    ``test_every_non_public_route_declares_policy`` asserts is empty, and
    is the guardrail that replaces fail-closed-everywhere enforcement in
    local/dev (ADR-018).

    Args:
        app: The FastAPI application.

    Returns:
        ``"METHODS path"`` strings for every offending route, for a
        readable assertion failure.
    """
    missing = []
    for route in iter_api_routes(getattr(app, "routes", [])):
        endpoint = route.endpoint
        if _is_excluded(endpoint) or is_public_endpoint(endpoint):
            continue
        if get_authorization_requirement(endpoint) is None:
            methods = ",".join(sorted(route.methods or []))
            missing.append(f"{methods} {route.path}")
    return sorted(missing)


def require_v2_principal(request: Request) -> PrincipalV2:
    """Return the principal :func:`enforce_control_plane_access` authenticated.

    Existing router-level ``dependencies=[Depends(require_v2_principal)]``
    and per-handler ``principal: PrincipalV2 = Depends(require_v2_principal)``
    signatures keep working unchanged; this only reads what the app-level
    dependency already stored.

    Args:
        request: The incoming request.

    Returns:
        The authenticated principal.
    """
    principal = getattr(request.state, "principal", None)
    assert isinstance(principal, PrincipalV2)
    return principal


def _resource_type(route: Any) -> str:
    """Derive a stable resource-area identifier from a matched route.

    Uses the route's first FastAPI tag (e.g. ``"sessions"``, ``"flows"``) as
    the audit trail's resource-area label; falls back to ``"unknown"`` for
    an unmatched route (should not occur once routing has resolved).

    Args:
        route: The Starlette/FastAPI route object from ``request.scope["route"]``.

    Returns:
        The resource-area label.
    """
    tags = getattr(route, "tags", None) or []
    return str(tags[0]) if tags else "unknown"


def _publish_unauthenticated_denial(
    *,
    resource_type: str,
    method: str,
    route_template: str,
    required_scope: str,
    request_id: str,
) -> None:
    """Best-effort publish a denial event for a failed authentication attempt.

    Not durably audited (ADR-018): there is no resolved tenant/subject to
    scope a durable row to, and requiring durability here would make
    anonymous/unauthenticated traffic able to trigger the same
    ``503 security.audit_unavailable`` fate reserved for genuine allowed
    requests.

    Args:
        resource_type: The matched route's resource-area label.
        method: HTTP method.
        route_template: The matched route's path template.
        required_scope: The route's declared required scope, if any.
        request_id: Correlation id for this request.
    """
    from backend.events.catalog import AccessRequestData  # noqa: PLC0415
    from backend.events.runtime import emit_event  # noqa: PLC0415

    payload = AccessRequestData(
        subjectId="anonymous",
        authMethod="unauthenticated",
        credentialId=None,
        roles=[],
        requiredScope=required_scope,
        resourceType=resource_type,
        resourceId=None,
        method=method,
        routeTemplate=route_template,
        decision="denied",
        reason="unauthenticated",
        requestId=request_id,
    )
    emit_event(
        "access.request.denied",
        tenant_id="system",
        partition_key="system",
        data=payload.model_dump(),
    )


async def enforce_control_plane_access(request: Request) -> None:
    """App-level dependency: authenticate, then authorize, every request.

    Installed once, on the FastAPI application itself, so it runs before
    every route — including ones contributed by auto-discovered plugin
    routers that never import this module. Order: public marker (skip
    entirely), authenticate (401 on failure), authorize against the
    route's declared scope (403 on missing policy in production, 403 on
    missing scope). Every decision made against a resolved principal —
    allowed or denied — is durably audited before the caller sees the
    result; a required-audit failure for an about-to-be-allowed request
    denies it (``503``) rather than letting an unauditable allow through
    (ADR-018). A failed *authentication* attempt (no principal resolved)
    is not durably audited — there is no tenant/subject to scope a durable
    row to — but still publishes a best-effort denial event.

    Args:
        request: The incoming request.

    Raises:
        HTTPException: 401 if no configured method authenticates the
            request; 403 if production finds no declared policy, or the
            principal lacks the required scope; 503 if a required audit
            write fails for an about-to-be-allowed request.
    """
    route = request.scope.get("route")
    endpoint = getattr(route, "endpoint", None)
    if endpoint is not None and is_public_endpoint(endpoint):
        return

    settings = Settings()
    service = get_auth_service()
    route_template = getattr(route, "path", request.url.path)
    resource_type = _resource_type(route)
    requirement = get_authorization_requirement(endpoint) if endpoint is not None else None
    required_scope = requirement.scope if requirement is not None else ""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())

    try:
        principal = await service.authenticate_request(request)
    except InvalidCredentialError as exc:
        _publish_unauthenticated_denial(
            resource_type=resource_type,
            method=request.method,
            route_template=route_template,
            required_scope=required_scope,
            request_id=request_id,
        )
        raise HTTPException(
            status_code=401,
            detail={"code": "authorization.unauthenticated", "message": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    request.state.principal = principal
    resource_id = (
        request.path_params.get(requirement.resource_parameter)
        if requirement is not None and requirement.resource_parameter
        else None
    )

    def _audit(*, decision: str, reason: str) -> AccessAuditRecord:
        return AccessAuditRecord(
            audit_id=new_audit_id(),
            occurred_at=utcnow(),
            tenant_id=principal.tenant_id,
            subject=principal.subject,
            auth_method=principal.auth_method,
            credential_id=principal.credential_id,
            roles=principal.roles,
            required_scope=required_scope,
            resource_type=resource_type,
            resource_id=resource_id,
            method=request.method,
            route_template=route_template,
            decision=decision,  # type: ignore[arg-type]
            reason=reason,
            request_id=request_id,
        )

    if requirement is None:
        if settings.autodev_profile == "prod":
            record = _audit(decision="denied", reason="policy_missing")
            try:
                get_audit_writer().record(record, required=False)
            except Exception:  # noqa: BLE001 - denial stands regardless of audit outcome
                pass
            else:
                publish_access_event(record)
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "authorization.policy_missing",
                    "message": "no authorization policy is declared for this route",
                },
            )
        return

    effective = effective_scopes(principal.roles, principal.scopes or None)
    if requirement.scope not in effective:
        record = _audit(decision="denied", reason="scope_missing")
        try:
            get_audit_writer().record(record, required=False)
        except Exception:  # noqa: BLE001 - denial stands regardless of audit outcome
            pass
        else:
            publish_access_event(record)
        raise HTTPException(
            status_code=403,
            detail={
                "code": "authorization.scope_missing",
                "message": f"missing required scope: {requirement.scope}",
            },
        )

    record = _audit(decision="allowed", reason="ok")
    try:
        get_audit_writer().record(record, required=True)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "security.audit_unavailable",
                "message": "access audit is unavailable; request denied",
            },
        ) from exc
    publish_access_event(record)


__all__ = [
    "enforce_control_plane_access",
    "get_authorization_requirement",
    "is_public_endpoint",
    "iter_api_routes",
    "protected_routes_without_requirement",
    "public_endpoint",
    "require_v2_principal",
    "requires_scope",
]
