"""v2 Control Plane API — OIDC login, sessions, and service credentials (E11-S2).

OIDC login/callback are public (no credential is presented yet). Every other
route here authenticates the request itself via
:meth:`~backend.auth.service.AuthService.authenticate_request` rather than
depending on the router-wide RBAC seam (:mod:`backend.api.rbac_v2`), because
this module ships before Task 3's global enforcement dependency exists and
must be independently correct. Service-credential management additionally
requires ``service_credential:admin`` once Task 3's authorization
enforcement is wired in (declared there, not here).
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.auth.contracts import AuthMethod, InvalidCredentialError, PrincipalV2
from backend.auth.oidc import build_authorization_url, exchange_code_for_tokens, generate_pkce_challenge
from backend.auth.roles import effective_scopes, normalize_role, normalize_scopes
from backend.auth.service import SESSION_COOKIE_NAME, get_auth_service
from backend.auth.store import utcnow
from backend.config.settings import get_settings

router = APIRouter(prefix="/v2/auth", tags=["auth"])

_PENDING_LOGIN_TTL_SECONDS = 600.0
_pending_logins: dict[str, tuple[str, str, float]] = {}
_pending_logins_lock = threading.Lock()


def _redirect_uri() -> str:
    """Build this application's registered OIDC callback URL.

    Returns:
        The absolute callback URL, derived from ``AUTODEV_UI_URL``'s origin
        joined with the callback path (the callback is served by this same
        backend, not the frontend).
    """
    settings = get_settings()
    origins = settings.cors_origins()
    origin = (origins[0] if origins else settings.autodev_ui_url).rstrip("/")
    return f"{origin}/v2/auth/oidc/callback"


def _prune_expired_logins(now: float) -> None:
    """Remove expired pending-login entries.

    Args:
        now: Current ``time.monotonic()`` reading.
    """
    expired = [state for state, (_, _, deadline) in _pending_logins.items() if deadline <= now]
    for state in expired:
        _pending_logins.pop(state, None)


async def _authenticated_principal(request: Request) -> PrincipalV2:
    """Authenticate one request and stash the principal on ``request.state``.

    Args:
        request: The incoming request.

    Returns:
        The authenticated principal.

    Raises:
        HTTPException: 401 if no configured method authenticates the request.
    """
    service = get_auth_service()
    try:
        principal = await service.authenticate_request(request)
    except InvalidCredentialError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    request.state.principal = principal
    return principal


class PrincipalResponseV2(BaseModel):
    """The authenticated caller, as returned by ``GET /v2/auth/me``."""

    model_config = ConfigDict(populate_by_name=True)

    subject: str
    tenant_id: str = Field(alias="tenantId")
    roles: list[str]
    scopes: list[str]
    auth_method: str = Field(alias="authMethod")


def _to_principal_response(principal: PrincipalV2) -> PrincipalResponseV2:
    """Convert an authenticated principal into its API response model."""
    scopes = sorted(effective_scopes(principal.roles, principal.scopes or None))
    return PrincipalResponseV2(
        subject=principal.subject,
        tenantId=principal.tenant_id,
        roles=[role.value for role in principal.roles],
        scopes=scopes,
        authMethod=principal.auth_method.value,
    )


class ServiceCredentialCreateRequestV2(BaseModel):
    """Request body for ``POST /v2/auth/service-credentials``."""

    subject: str = Field(..., min_length=1)
    roles: list[str] = Field(..., min_length=1)
    scopes: list[str] = Field(default_factory=list)
    expires_in_days: int = Field(alias="expiresInDays", ge=1, le=90)

    model_config = ConfigDict(populate_by_name=True)


class ServiceCredentialResponseV2(BaseModel):
    """A service credential, as returned by list/create/revoke."""

    model_config = ConfigDict(populate_by_name=True)

    key_id: str = Field(alias="keyId")
    subject: str
    roles: list[str]
    scopes: list[str]
    created_at: str = Field(alias="createdAt")
    expires_at: str = Field(alias="expiresAt")
    key: str | None = None


def _to_credential_response(record: object, *, key: str | None = None) -> ServiceCredentialResponseV2:
    """Convert a persisted service credential into its API response model."""
    from backend.auth.contracts import ServiceCredentialRecord  # noqa: PLC0415

    assert isinstance(record, ServiceCredentialRecord)
    return ServiceCredentialResponseV2(
        keyId=record.key_id,
        subject=record.subject,
        roles=[role.value for role in record.roles],
        scopes=sorted(record.scopes),
        createdAt=record.created_at.isoformat(),
        expiresAt=record.expires_at.isoformat(),
        key=key,
    )


@router.get("/oidc/login", include_in_schema=True)
def oidc_login_v2(returnTo: str = "/") -> RedirectResponse:  # noqa: N803 - query param name is a public contract
    """Start an OIDC authorization-code + PKCE login.

    Args:
        returnTo: Relative path to redirect to after a successful login.
            Absolute/external URLs are rejected in favor of ``/``.

    Returns:
        A redirect to the OIDC provider's authorization endpoint.

    Raises:
        HTTPException: 404 if OIDC is not configured.
    """
    service = get_auth_service()
    if not service.oidc_settings.is_configured:
        raise HTTPException(status_code=404, detail="OIDC is not configured")
    safe_return_to = returnTo if returnTo.startswith("/") and not returnTo.startswith("//") else "/"
    challenge = generate_pkce_challenge()
    with _pending_logins_lock:
        now = time.monotonic()
        _prune_expired_logins(now)
        _pending_logins[challenge.state] = (
            challenge.code_verifier,
            safe_return_to,
            now + _PENDING_LOGIN_TTL_SECONDS,
        )
    authorization_url = build_authorization_url(
        service.oidc_settings, challenge=challenge, redirect_uri=_redirect_uri()
    )
    return RedirectResponse(authorization_url, status_code=302)


@router.get("/oidc/callback", include_in_schema=True)
async def oidc_callback_v2(code: str, state: str) -> Response:
    """Complete an OIDC login: exchange the code, mint a session.

    Args:
        code: Authorization code returned by the provider.
        state: Anti-CSRF state matching a pending login started by
            :func:`oidc_login_v2`.

    Returns:
        A redirect to the original ``returnTo`` path with an HttpOnly,
        Secure session cookie set.

    Raises:
        HTTPException: 400 if ``state`` does not match a pending login; 502
            if the provider rejects the code exchange.
    """
    service = get_auth_service()
    with _pending_logins_lock:
        pending = _pending_logins.pop(state, None)
    if pending is None:
        raise HTTPException(status_code=400, detail="invalid or expired login state")
    code_verifier, return_to, _deadline = pending

    tokens = await exchange_code_for_tokens(
        service.oidc_settings,
        code=code,
        code_verifier=code_verifier,
        redirect_uri=_redirect_uri(),
    )
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=502, detail="OIDC provider did not return an id_token")
    principal = service.authenticate_oidc_bearer(str(id_token))
    record = service.create_session(
        tenant_id=principal.tenant_id,
        subject=principal.subject,
        roles=principal.roles,
        refresh_token=str(tokens.get("refresh_token") or ""),
    )

    response = RedirectResponse(return_to, status_code=302)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        record.session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=int((record.expires_at - utcnow()).total_seconds()),
        path="/",
    )
    return response


@router.get("/me", response_model=PrincipalResponseV2)
async def get_me_v2(request: Request) -> PrincipalResponseV2:
    """Return the calling principal's identity, roles, and effective scopes.

    Args:
        request: The incoming request, authenticated inline.

    Returns:
        The authenticated principal's public representation.
    """
    principal = await _authenticated_principal(request)
    return _to_principal_response(principal)


@router.post("/session/refresh", response_model=PrincipalResponseV2)
async def refresh_session_v2(request: Request, response: Response) -> PrincipalResponseV2:
    """Rotate the caller's browser session using its refresh token.

    Args:
        request: The incoming request, authenticated inline.
        response: Outgoing response, updated with the rotated session cookie.

    Returns:
        The refreshed principal.

    Raises:
        HTTPException: 400 if the caller does not have an active session.
    """
    principal = await _authenticated_principal(request)
    if principal.auth_method != AuthMethod.SESSION or principal.credential_id is None:
        raise HTTPException(status_code=400, detail="no active session to refresh")
    service = get_auth_service()
    try:
        record = await service.refresh_session(principal.credential_id)
    except InvalidCredentialError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    response.set_cookie(
        SESSION_COOKIE_NAME,
        record.session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=int((record.expires_at - utcnow()).total_seconds()),
        path="/",
    )
    return _to_principal_response(
        PrincipalV2(
            subject=record.subject,
            tenant_id=record.tenant_id,
            roles=record.roles,
            scopes=frozenset(),
            auth_method=AuthMethod.SESSION,
            credential_id=record.session_id,
            expires_at=record.expires_at,
        )
    )


@router.delete("/session", status_code=204)
async def logout_v2(request: Request, response: Response) -> Response:
    """Log out: revoke the caller's session and clear its cookie.

    Args:
        request: The incoming request, authenticated inline.
        response: Outgoing response, updated to clear the session cookie.

    Returns:
        An empty ``204`` response.
    """
    principal = await _authenticated_principal(request)
    service = get_auth_service()
    if principal.credential_id and principal.auth_method == AuthMethod.SESSION:
        service.revoke_session(principal.credential_id)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return Response(status_code=204)


@router.get("/service-credentials", response_model=list[ServiceCredentialResponseV2])
async def list_service_credentials_v2(request: Request) -> list[ServiceCredentialResponseV2]:
    """List every service credential for the caller's tenant.

    Args:
        request: The incoming request, authenticated inline.

    Returns:
        The tenant's service credentials. Never includes a secret.
    """
    principal = await _authenticated_principal(request)
    service = get_auth_service()
    records = service.list_service_keys(tenant_id=principal.tenant_id)
    return [_to_credential_response(record) for record in records]


@router.post(
    "/service-credentials",
    response_model=ServiceCredentialResponseV2,
    status_code=201,
)
async def create_service_credential_v2(
    request: Request, body: ServiceCredentialCreateRequestV2
) -> ServiceCredentialResponseV2:
    """Mint a new service credential for the caller's tenant.

    Args:
        request: The incoming request, authenticated inline.
        body: The credential's subject, roles, scopes, and expiry.

    Returns:
        The persisted credential, including the one-time presented key.

    Raises:
        HTTPException: 400 if the requested scopes exceed the requested
            roles' grants.
    """
    principal = await _authenticated_principal(request)
    service = get_auth_service()
    try:
        roles = tuple(normalize_role(item) for item in body.roles)
        scopes = normalize_scopes(body.scopes) if body.scopes else frozenset()
        record, key = service.create_service_key(
            tenant_id=principal.tenant_id,
            subject=body.subject,
            roles=roles,
            scopes=scopes,
            expires_at=utcnow() + timedelta(days=body.expires_in_days),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_credential_response(record, key=key)


@router.delete("/service-credentials/{key_id}", status_code=204)
async def revoke_service_credential_v2(request: Request, key_id: str) -> Response:
    """Immediately revoke a service credential owned by the caller's tenant.

    Args:
        request: The incoming request, authenticated inline.
        key_id: The credential's non-secret identifier.

    Returns:
        An empty ``204`` response.

    Raises:
        HTTPException: 404 if the credential does not exist or belongs to
            another tenant.
    """
    principal = await _authenticated_principal(request)
    service = get_auth_service()
    if not service.revoke_service_key(tenant_id=principal.tenant_id, key_id=key_id):
        raise HTTPException(status_code=404, detail="unknown service credential")
    return Response(status_code=204)


# Exposed for Task 3's authorization enforcement, which marks the login and
# callback routes as public without needing to know this module's internals.
PUBLIC_ROUTE_NAMES: frozenset[str] = frozenset({"oidc_login_v2", "oidc_callback_v2"})


__all__ = [
    "PUBLIC_ROUTE_NAMES",
    "PrincipalResponseV2",
    "ServiceCredentialResponseV2",
    "router",
]
