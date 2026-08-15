"""Request authentication and credential/session lifecycle (E11-S2 Task 2).

:class:`AuthService` is the single place that turns a presented credential —
a service key, the legacy compatibility PAT, an OIDC bearer JWT, a session
cookie, or nothing at all in local zero-config mode — into a
:class:`~backend.auth.contracts.PrincipalV2`. Route-level authorization
(Task 3) and audit persistence (Task 4) are deliberately layered on top of
this module rather than folded into it.
"""

from __future__ import annotations

import hmac
import secrets
import threading
from datetime import timedelta
from typing import Any

from fastapi import Request

from backend.auth.contracts import (
    AuthMethod,
    AuthSessionRecord,
    InvalidCredentialError,
    PrincipalV2,
    Role,
    ServiceCredentialRecord,
)
from backend.auth.crypto import (
    SERVICE_KEY_PREFIX,
    decrypt_refresh_token,
    derive_fernet,
    encrypt_refresh_token,
    generate_key_id,
    generate_service_key,
    parse_service_key,
    verify_secret,
)
from backend.auth.oidc import OidcValidator, build_oidc_settings, refresh_access_token
from backend.auth.roles import effective_scopes
from backend.auth.store import AuthStore, utcnow

SESSION_COOKIE_NAME = "autodev_session"
_MIN_SERVICE_KEY_TTL = timedelta(days=1)
_MAX_SERVICE_KEY_TTL = timedelta(days=90)
# A caller (or CLI/API request) computes `expires_at` from its own `now()`
# reading, then this validation re-reads `now()` again slightly later —
# without slack, any request for exactly the 1-day minimum would always be
# rejected as a few milliseconds "too short".
_SERVICE_KEY_TTL_CLOCK_SLACK = timedelta(minutes=5)

_ephemeral_session_key: str | None = None
_ephemeral_session_key_lock = threading.Lock()


def _local_ephemeral_session_key() -> str:
    """Return one process-lifetime random session-encryption key.

    Used only when ``AUTODEV_SESSION_ENCRYPTION_KEY`` is unset (local mode).
    Cached at module level rather than per :class:`AuthService` instance —
    :class:`AuthService` is constructed fresh per request/call (matching
    this codebase's other per-request service providers, e.g.
    ``sessions_v2.get_orchestrator_v2``), so a per-instance key would make a
    session encrypted by one request undecryptable by the next.
    """
    global _ephemeral_session_key
    if _ephemeral_session_key is None:
        with _ephemeral_session_key_lock:
            if _ephemeral_session_key is None:
                _ephemeral_session_key = secrets.token_urlsafe(32)
    return _ephemeral_session_key


def _reset_ephemeral_session_key() -> None:
    """Clear the cached local ephemeral session key — for use in tests."""
    global _ephemeral_session_key
    _ephemeral_session_key = None


class AuthService:
    """Authenticates requests and manages service-credential/session lifecycle."""

    def __init__(self, settings: Any, store: AuthStore | None = None) -> None:
        """Build an auth service bound to one settings/store pair.

        Args:
            settings: The application :class:`~backend.config.settings.Settings`.
            store: Durable Auth Store; defaults to a new :class:`AuthStore`.
        """
        self._settings = settings
        self._store = store or AuthStore()
        self._oidc_settings = build_oidc_settings(settings)
        self._validator = (
            OidcValidator(self._oidc_settings) if self._oidc_settings.jwks_url else None
        )
        key_material = (
            settings.autodev_session_encryption_key.strip() or _local_ephemeral_session_key()
        )
        self._fernet = derive_fernet(key_material)

    @property
    def oidc_settings(self) -> Any:
        """The resolved OIDC configuration this service validates against."""
        return self._oidc_settings

    @property
    def store(self) -> AuthStore:
        """The durable Auth Store this service persists credentials/sessions to."""
        return self._store

    def _is_local_zero_config(self) -> bool:
        """Whether this process is in the documented local, zero-config trust state."""
        return (
            self._settings.autodev_profile == "local"
            and not self._settings.autodev_api_token.strip()
            and not self._oidc_settings.is_configured
        )

    def authenticate_local_request(self) -> PrincipalV2:
        """Build the fully-open local zero-config principal.

        Returns:
            An owner-equivalent principal for tenant ``default``, subject
            ``local``.
        """
        return PrincipalV2(
            subject="local",
            tenant_id="default",
            roles=(Role.OWNER,),
            scopes=frozenset(),
            auth_method=AuthMethod.LOCAL,
        )

    def authenticate_legacy_pat(self, presented: str) -> PrincipalV2 | None:
        """Authenticate against the legacy ``AUTODEV_API_TOKEN`` compatibility PAT.

        Args:
            presented: The bearer token presented by the caller.

        Returns:
            An admin-equivalent principal if ``presented`` matches the
            configured token; ``None`` if no token is configured or it does
            not match (so the caller can fall through to another method).
        """
        token = self._settings.autodev_api_token.strip()
        if not token or not hmac.compare_digest(presented, token):
            return None
        return PrincipalV2(
            subject="legacy",
            tenant_id="default",
            roles=(Role.ADMIN,),
            scopes=frozenset(),
            auth_method=AuthMethod.LEGACY_PAT,
        )

    def authenticate_service_key(self, presented: str) -> PrincipalV2:
        """Authenticate a presented ``adk_live_<key-id>_<secret>`` service key.

        Args:
            presented: The full presented service key.

        Returns:
            The service credential's principal.

        Raises:
            InvalidCredentialError: If the key is malformed, unknown,
                revoked, expired, or the secret does not match.
        """
        parsed = parse_service_key(presented)
        if parsed is None:
            raise InvalidCredentialError("malformed service key")
        key_id, secret = parsed
        record = self._store.get_service_credential(key_id)
        if record is None or not record.is_active or record.expires_at <= utcnow():
            raise InvalidCredentialError("unknown or inactive service key")
        if not verify_secret(secret, record.secret_hash):
            raise InvalidCredentialError("invalid service key secret")
        return PrincipalV2(
            subject=record.subject,
            tenant_id=record.tenant_id,
            roles=record.roles,
            scopes=record.scopes,
            auth_method=AuthMethod.SERVICE_KEY,
            credential_id=record.key_id,
            expires_at=record.expires_at,
        )

    def authenticate_oidc_bearer(self, token: str) -> PrincipalV2:
        """Authenticate a presented OIDC bearer JWT.

        Args:
            token: The raw bearer JWT.

        Returns:
            The validated principal.

        Raises:
            InvalidCredentialError: If OIDC is not configured or the token
                fails validation.
        """
        if self._validator is None:
            raise InvalidCredentialError("OIDC is not configured")
        return self._validator.validate(token)

    def authenticate_session(self, presented: str) -> PrincipalV2:
        """Authenticate a presented browser session id.

        Args:
            presented: The session cookie's value.

        Returns:
            The session's principal.

        Raises:
            InvalidCredentialError: If the session is unknown, revoked, or
                expired.
        """
        record = self._store.get_session(presented)
        if record is None or not record.is_active or record.expires_at <= utcnow():
            raise InvalidCredentialError("unknown or inactive session")
        return PrincipalV2(
            subject=record.subject,
            tenant_id=record.tenant_id,
            roles=record.roles,
            scopes=frozenset(),
            auth_method=AuthMethod.SESSION,
            credential_id=record.session_id,
            expires_at=record.expires_at,
        )

    async def authenticate_request(self, request: Request) -> PrincipalV2:
        """Authenticate one HTTP request against every configured method.

        Order: bearer service key, legacy PAT, OIDC bearer JWT, session
        cookie, local zero-config. Callers are expected to have already
        short-circuited public routes before calling this.

        Args:
            request: The incoming request.

        Returns:
            The authenticated principal.

        Raises:
            InvalidCredentialError: If no method authenticates the request.
        """
        auth_header = request.headers.get("Authorization", "")
        presented_bearer = (
            auth_header[7:].strip() if auth_header[:7].lower() == "bearer " else ""
        )

        if presented_bearer:
            if presented_bearer.startswith(f"{SERVICE_KEY_PREFIX}_"):
                return self.authenticate_service_key(presented_bearer)
            legacy = self.authenticate_legacy_pat(presented_bearer)
            if legacy is not None:
                return legacy
            return self.authenticate_oidc_bearer(presented_bearer)

        session_cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
        if session_cookie:
            return self.authenticate_session(session_cookie)

        if self._is_local_zero_config():
            return self.authenticate_local_request()

        raise InvalidCredentialError("missing credentials")

    def create_service_key(
        self,
        *,
        tenant_id: str,
        subject: str,
        roles: tuple[Role, ...],
        scopes: frozenset[str],
        expires_at: Any,
    ) -> tuple[ServiceCredentialRecord, str]:
        """Mint and persist a new service credential.

        Args:
            tenant_id: Tenant the credential authenticates into.
            subject: Human-readable subject the credential is issued to.
            roles: Canonical roles the credential authenticates as.
            scopes: Requested scopes, narrowing ``roles``' grant; empty for
                the unnarrowed grant.
            expires_at: When the credential expires (1-90 days from now).

        Returns:
            The persisted record and the one-time presented key. The
            presented key is never recoverable again — only its hash is
            stored.

        Raises:
            ValueError: If ``expires_at`` is outside 1-90 days from now, or
                ``scopes`` exceeds what ``roles`` grants.
        """
        now = utcnow()
        ttl = expires_at - now
        if not (
            _MIN_SERVICE_KEY_TTL - _SERVICE_KEY_TTL_CLOCK_SLACK
            <= ttl
            <= _MAX_SERVICE_KEY_TTL + _SERVICE_KEY_TTL_CLOCK_SLACK
        ):
            raise ValueError("service key expiry must be between 1 and 90 days from now")
        granted = effective_scopes(roles, None)
        if scopes and not scopes <= granted:
            raise ValueError("requested scopes exceed the role's grants")

        key_id = generate_key_id()
        presented_key, secret_hash = generate_service_key(key_id)
        record = ServiceCredentialRecord(
            key_id=key_id,
            tenant_id=tenant_id,
            subject=subject,
            secret_hash=secret_hash,
            roles=roles,
            scopes=scopes,
            created_at=now,
            expires_at=expires_at,
        )
        self._store.create_service_credential(record)
        return record, presented_key

    def revoke_service_key(self, *, tenant_id: str, key_id: str) -> bool:
        """Immediately revoke a service credential.

        Args:
            tenant_id: Tenant that must own the credential.
            key_id: The credential's non-secret identifier.

        Returns:
            ``True`` if an active credential was revoked.
        """
        return self._store.revoke_service_credential(tenant_id=tenant_id, key_id=key_id)

    def list_service_keys(self, *, tenant_id: str) -> list[ServiceCredentialRecord]:
        """List every service credential belonging to one tenant.

        Args:
            tenant_id: Tenant to scope the listing to.

        Returns:
            The tenant's credentials. Never includes a secret or its hash's
            plaintext equivalent to callers outside this module.
        """
        return self._store.list_service_credentials(tenant_id=tenant_id)

    def create_session(
        self, *, tenant_id: str, subject: str, roles: tuple[Role, ...], refresh_token: str
    ) -> AuthSessionRecord:
        """Create and persist a new browser session after an OIDC login.

        Args:
            tenant_id: Tenant the session's principal acts within.
            subject: OIDC ``sub`` this session belongs to.
            roles: Canonical roles resolved at login time.
            refresh_token: The raw OIDC refresh token, encrypted before storage.

        Returns:
            The persisted session record.
        """
        now = utcnow()
        record = AuthSessionRecord(
            session_id=secrets.token_urlsafe(32),
            tenant_id=tenant_id,
            subject=subject,
            roles=roles,
            encrypted_refresh_token=encrypt_refresh_token(refresh_token, self._fernet),
            created_at=now,
            expires_at=now + timedelta(seconds=self._settings.autodev_session_ttl_seconds),
        )
        self._store.create_session(record)
        return record

    def decrypt_session_refresh_token(self, record: AuthSessionRecord) -> str:
        """Decrypt one session's stored refresh token.

        Args:
            record: The session whose refresh token should be decrypted.

        Returns:
            The raw OIDC refresh token.
        """
        return decrypt_refresh_token(record.encrypted_refresh_token, self._fernet)

    def revoke_session(self, session_id: str) -> bool:
        """Revoke a browser session (logout).

        Args:
            session_id: The session cookie's value.

        Returns:
            ``True`` if an active session was revoked.
        """
        return self._store.revoke_session(session_id)

    def get_session_record(self, session_id: str) -> AuthSessionRecord | None:
        """Fetch the raw session record for a session id.

        Args:
            session_id: The session cookie's value.

        Returns:
            The session record, or ``None`` if unknown.
        """
        return self._store.get_session(session_id)

    async def refresh_session(self, session_id: str) -> AuthSessionRecord:
        """Rotate a session: exchange its refresh token, then reissue.

        The old session is revoked and a new one is created so a stolen
        session id cannot be replayed after a legitimate refresh.

        Args:
            session_id: The session cookie's value to refresh.

        Returns:
            The newly created session record.

        Raises:
            InvalidCredentialError: If the session is unknown/inactive or
                the provider rejects the refresh token.
        """
        record = self._store.get_session(session_id)
        if record is None or not record.is_active:
            raise InvalidCredentialError("unknown or inactive session")
        refresh_token = self.decrypt_session_refresh_token(record)
        tokens = await refresh_access_token(self._oidc_settings, refresh_token=refresh_token)
        new_refresh_token = str(tokens.get("refresh_token") or refresh_token)
        self._store.revoke_session(session_id)
        return self.create_session(
            tenant_id=record.tenant_id,
            subject=record.subject,
            roles=record.roles,
            refresh_token=new_refresh_token,
        )


def get_auth_service() -> AuthService:
    """Build an :class:`AuthService` bound to the current application settings.

    Constructed fresh on every call, from an uncached ``Settings()`` read —
    matching both this codebase's per-request ``/v2`` service-provider
    convention (``get_orchestrator_v2``, ``get_flow_engine``, ...) *and*
    ``backend.api.security.require_api_token``'s existing pattern of
    reading a fresh ``Settings()`` rather than the ``lru_cache``d
    ``get_settings()``. That second point matters here specifically: many
    existing tests toggle env vars (``AUTODEV_API_TOKEN``, OIDC settings)
    mid-test via ``monkeypatch.setenv`` without calling
    ``reset_settings_cache()``, and this security-gating path must observe
    that change on the very next request, the same way ``require_api_token``
    already does.

    Local mode's ephemeral session-encryption key stays stable across these
    fresh constructions via a separate, narrowly-scoped module cache (see
    :func:`_local_ephemeral_session_key`); the underlying Auth Store
    connection is likewise shared via :func:`backend.persistence.database.get_store`'s
    own cache, so this is not a fresh SQLite connection per call.

    Returns:
        A new :class:`AuthService` bound to a freshly read ``Settings()``.
    """
    from backend.config.settings import Settings  # noqa: PLC0415

    return AuthService(Settings())


def reset_auth_service_cache() -> None:
    """Clear auth-service-adjacent process caches — for use in tests.

    ``get_auth_service()`` itself is no longer cached, but the local
    ephemeral session-encryption key is; this resets that, so a test that
    wants a truly clean slate (e.g. asserting session behavior in
    isolation) can get one.
    """
    _reset_ephemeral_session_key()


__all__ = [
    "SESSION_COOKIE_NAME",
    "AuthService",
    "get_auth_service",
    "reset_auth_service_cache",
]
