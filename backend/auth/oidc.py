"""OIDC/JWKS bearer-token validation and authorization-code + PKCE login.

JWT signature verification and JWKS caching are delegated to PyJWT's
:class:`jwt.PyJWKClient` (built-in TTL cache, one refetch on an unknown
``kid``) rather than hand-rolled, matching the story's "reuse, don't
reinvent" constraint. The algorithm allowlist is always supplied explicitly
to :func:`jwt.decode` — the token header's own ``alg`` is never trusted to
select the verification algorithm, which is what prevents the classic
algorithm-confusion downgrade attack.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from backend.auth.contracts import AuthMethod, InvalidCredentialError, PrincipalV2
from backend.auth.roles import normalize_role, normalize_scopes


@dataclass(frozen=True, slots=True)
class OidcSettings:
    """Resolved OIDC configuration required to validate and issue logins.

    Attributes:
        issuer: Expected JWT ``iss`` claim.
        audience: Expected JWT ``aud`` claim.
        jwks_url: HTTPS JWKS endpoint.
        authorization_url: Provider's authorization endpoint.
        token_url: Provider's token endpoint.
        client_id: This application's registered OIDC client id.
        client_secret: This application's registered OIDC client secret.
        role_claim: Claim name carrying the caller's role(s).
        tenant_claim: Claim name carrying the caller's tenant id.
        scope_claim: Claim name carrying the caller's asserted scopes.
        algorithms: Allowed JWS signing algorithms.
        jwks_ttl_seconds: How long a fetched JWKS key set is cached.
    """

    issuer: str
    audience: str
    jwks_url: str
    authorization_url: str
    token_url: str
    client_id: str
    client_secret: str
    role_claim: str
    tenant_claim: str
    scope_claim: str
    algorithms: tuple[str, ...]
    jwks_ttl_seconds: int

    @property
    def is_configured(self) -> bool:
        """Whether every setting required to validate/issue tokens is present."""
        return bool(
            self.issuer
            and self.audience
            and self.jwks_url
            and self.authorization_url
            and self.token_url
            and self.client_id
        )


def build_oidc_settings(settings: Any) -> OidcSettings:
    """Resolve :class:`OidcSettings` from application settings.

    Args:
        settings: The :class:`backend.config.settings.Settings` instance.

    Returns:
        The resolved OIDC configuration.

    Raises:
        ValueError: If a non-empty JWKS URL does not use HTTPS.
    """
    jwks_url = settings.autodev_oidc_jwks_url.strip()
    if jwks_url and not jwks_url.startswith("https://"):
        raise ValueError("AUTODEV_OIDC_JWKS_URL must use HTTPS")
    algorithms = tuple(
        item.strip()
        for item in settings.autodev_oidc_algorithms.split(",")
        if item.strip()
    )
    return OidcSettings(
        issuer=settings.autodev_oidc_issuer.strip(),
        audience=settings.autodev_oidc_audience.strip(),
        jwks_url=jwks_url,
        authorization_url=settings.autodev_oidc_authorization_url.strip(),
        token_url=settings.autodev_oidc_token_url.strip(),
        client_id=settings.autodev_oidc_client_id.strip(),
        client_secret=settings.autodev_oidc_client_secret.strip(),
        role_claim=settings.autodev_oidc_role_claim.strip() or "roles",
        tenant_claim=settings.autodev_oidc_tenant_claim.strip() or "tenant_id",
        scope_claim=settings.autodev_oidc_scope_claim.strip() or "scope",
        algorithms=algorithms or ("RS256",),
        jwks_ttl_seconds=settings.autodev_oidc_jwks_ttl_seconds,
    )


class OidcValidator:
    """Validates OIDC bearer JWTs into typed principals."""

    def __init__(self, oidc_settings: OidcSettings) -> None:
        """Build a validator bound to one resolved OIDC configuration.

        Args:
            oidc_settings: The provider configuration to validate against.
        """
        self._settings = oidc_settings
        self._jwks_client = (
            PyJWKClient(oidc_settings.jwks_url, cache_keys=True, lifespan=oidc_settings.jwks_ttl_seconds)
            if oidc_settings.jwks_url
            else None
        )

    def validate(self, token: str) -> PrincipalV2:
        """Validate a bearer JWT and build its :class:`PrincipalV2`.

        Validates ``iss``, ``aud``, ``exp``, ``sub``, the tenant claim, the
        role claim, the scope claim, and the JWKS signature, against the
        configured algorithm allowlist.

        Args:
            token: The raw bearer JWT.

        Returns:
            The authenticated principal.

        Raises:
            InvalidCredentialError: If the token is malformed, unsigned by a
                known key, expired, wrong issuer/audience, or missing a
                required claim.
        """
        if self._jwks_client is None:
            raise InvalidCredentialError("OIDC is not configured")
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self._settings.algorithms),
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidCredentialError(f"invalid OIDC token: {exc}") from exc

        subject = claims.get("sub")
        tenant_id = claims.get(self._settings.tenant_claim)
        if not subject or not tenant_id:
            raise InvalidCredentialError("OIDC token missing sub or tenant claim")

        raw_roles = claims.get(self._settings.role_claim) or []
        role_values = raw_roles if isinstance(raw_roles, list) else [raw_roles]
        try:
            roles = tuple(normalize_role(str(value)) for value in role_values)
        except ValueError as exc:
            raise InvalidCredentialError(str(exc)) from exc
        if not roles:
            raise InvalidCredentialError("OIDC token missing role claim")

        raw_scope = claims.get(self._settings.scope_claim) or ""
        scopes = normalize_scopes(raw_scope) if raw_scope else frozenset()

        expires_at = (
            datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
            if "exp" in claims
            else None
        )
        return PrincipalV2(
            subject=str(subject),
            tenant_id=str(tenant_id),
            roles=roles,
            scopes=scopes,
            auth_method=AuthMethod.OIDC,
            expires_at=expires_at,
        )


@dataclass(frozen=True, slots=True)
class PkceChallenge:
    """One S256 PKCE code verifier/challenge pair, plus anti-CSRF state.

    Attributes:
        state: Opaque anti-CSRF token round-tripped through the provider.
        code_verifier: Secret kept server-side (in the pending-login store)
            until the callback.
        code_challenge: The ``S256`` hash of ``code_verifier``, sent in the
            authorization request.
    """

    state: str
    code_verifier: str
    code_challenge: str


def generate_pkce_challenge() -> PkceChallenge:
    """Generate one S256 PKCE verifier/challenge pair and anti-CSRF state.

    Returns:
        A fresh :class:`PkceChallenge`.
    """
    state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkceChallenge(state=state, code_verifier=code_verifier, code_challenge=code_challenge)


def build_authorization_url(
    oidc_settings: OidcSettings, *, challenge: PkceChallenge, redirect_uri: str
) -> str:
    """Build the OIDC authorization-code + PKCE redirect URL.

    Args:
        oidc_settings: The provider configuration.
        challenge: The PKCE challenge generated for this login attempt.
        redirect_uri: This application's registered callback URL.

    Returns:
        The fully-formed authorization URL to redirect the browser to.
    """
    query = httpx.QueryParams(
        {
            "response_type": "code",
            "client_id": oidc_settings.client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile",
            "state": challenge.state,
            "code_challenge": challenge.code_challenge,
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in oidc_settings.authorization_url else "?"
    return f"{oidc_settings.authorization_url}{separator}{query}"


async def exchange_code_for_tokens(
    oidc_settings: OidcSettings,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens at the provider's token endpoint.

    Args:
        oidc_settings: The provider configuration.
        code: The authorization code returned to the callback.
        code_verifier: The PKCE verifier generated for this login attempt.
        redirect_uri: This application's registered callback URL (must match
            the one used to build the authorization URL).
        client: Optional injected HTTP client, for tests.

    Returns:
        The decoded token response (``id_token``, ``access_token``,
        ``refresh_token``, ``expires_in``).

    Raises:
        InvalidCredentialError: If the token endpoint rejects the exchange.
    """
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": oidc_settings.client_id,
        "client_secret": oidc_settings.client_secret,
        "code_verifier": code_verifier,
    }
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await active_client.post(oidc_settings.token_url, data=payload)
        if response.status_code != 200:
            raise InvalidCredentialError("OIDC token exchange failed")
        return dict(response.json())
    finally:
        if owns_client:
            await active_client.aclose()


async def refresh_access_token(
    oidc_settings: OidcSettings,
    *,
    refresh_token: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Exchange a refresh token for a new token set.

    Args:
        oidc_settings: The provider configuration.
        refresh_token: The session's decrypted refresh token.
        client: Optional injected HTTP client, for tests.

    Returns:
        The decoded token response.

    Raises:
        InvalidCredentialError: If the provider rejects the refresh token.
    """
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": oidc_settings.client_id,
        "client_secret": oidc_settings.client_secret,
    }
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await active_client.post(oidc_settings.token_url, data=payload)
        if response.status_code != 200:
            raise InvalidCredentialError("OIDC token refresh failed")
        return dict(response.json())
    finally:
        if owns_client:
            await active_client.aclose()


__all__ = [
    "OidcSettings",
    "OidcValidator",
    "PkceChallenge",
    "build_authorization_url",
    "build_oidc_settings",
    "exchange_code_for_tokens",
    "generate_pkce_challenge",
    "refresh_access_token",
]
