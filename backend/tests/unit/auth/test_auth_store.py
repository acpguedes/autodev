"""Contracts for AuthStore, AuthService, and production readiness (Task 2)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from backend.auth.contracts import AuthReadinessError, InvalidCredentialError, Role
from backend.auth.readiness import validate_auth_readiness
from backend.auth.service import AuthService
from backend.auth.store import AuthStore, utcnow
from backend.config.settings import Settings
from backend.persistence.sqlite_adapter import SQLiteStore


def _store(tmp_path: Path) -> AuthStore:
    return AuthStore(SQLiteStore(f"sqlite:///{tmp_path / 'auth.db'}"))


def local_settings(**overrides: object) -> Settings:
    """Build local-profile settings with SQLite persistence."""
    return Settings(autodev_profile="local", database_url="sqlite:///./unused.db", **overrides)


def prod_settings(**overrides: object) -> Settings:
    """Build production-profile settings satisfying every non-auth constraint."""
    return Settings(
        autodev_profile="prod",
        database_url="postgresql://user:pass@localhost/autodev",
        autodev_job_backend="redis",
        autodev_event_bus="redis",
        autodev_redis_url="redis://localhost:6379/0",
        storage_backend="s3",
        autodev_minio_endpoint="minio:9000",
        autodev_minio_access_key="key",
        autodev_minio_secret_key="secret",
        **overrides,
    )


def auth_service_for(tmp_path: Path, *, settings: Settings | None = None) -> AuthService:
    """Build an AuthService bound to a fresh SQLite-backed AuthStore."""
    return AuthService(settings or local_settings(), _store(tmp_path))


def test_local_zero_config_remains_open() -> None:
    """The local profile with no configured credential yields an open owner principal."""
    principal = AuthService(local_settings()).authenticate_local_request()
    assert principal.tenant_id == "default"
    assert principal.roles == (Role.OWNER,)


def test_production_without_oidc_or_service_key_fails(tmp_path: Path) -> None:
    """Production refuses to start with neither OIDC nor an active service credential."""
    with pytest.raises(AuthReadinessError, match="OIDC/JWKS or an active service credential"):
        validate_auth_readiness(prod_settings(), _store(tmp_path))


def test_legacy_pat_does_not_satisfy_production(tmp_path: Path) -> None:
    """The legacy compatibility PAT alone never satisfies production readiness."""
    settings = prod_settings(autodev_api_token="legacy")
    with pytest.raises(AuthReadinessError):
        validate_auth_readiness(settings, _store(tmp_path))


def test_production_with_active_service_credential_passes(tmp_path: Path) -> None:
    """An active service credential alone is a sufficient production bootstrap."""
    settings = prod_settings()
    service = auth_service_for(tmp_path, settings=settings)
    service.create_service_key(
        tenant_id="tenant-a",
        subject="ci",
        roles=(Role.OPERATOR,),
        scopes=frozenset(),
        expires_at=utcnow() + timedelta(days=30),
    )
    validate_auth_readiness(settings, service.store)


def test_production_with_configured_oidc_passes(tmp_path: Path) -> None:
    """Complete OIDC/JWKS settings alone are a sufficient production bootstrap."""
    settings = prod_settings(
        autodev_oidc_issuer="https://idp.example.com",
        autodev_oidc_audience="autodev",
        autodev_oidc_jwks_url="https://idp.example.com/.well-known/jwks.json",
        autodev_oidc_authorization_url="https://idp.example.com/authorize",
        autodev_oidc_token_url="https://idp.example.com/token",
        autodev_oidc_client_id="autodev-backend",
    )
    validate_auth_readiness(settings, _store(tmp_path))


def test_service_key_is_hash_only_and_revocable(tmp_path: Path) -> None:
    """A minted service key's secret is never stored, and revocation is immediate."""
    service = auth_service_for(tmp_path)
    record, secret = service.create_service_key(
        tenant_id="tenant-a",
        subject="ci",
        roles=(Role.OPERATOR,),
        scopes=frozenset({"run:read", "run:write"}),
        expires_at=utcnow() + timedelta(days=30),
    )
    assert secret.startswith(f"adk_live_{record.key_id}_")

    db_text = (tmp_path / "auth.db").read_bytes()
    assert secret.encode("utf-8") not in db_text

    principal = service.authenticate_service_key(secret)
    assert principal.tenant_id == "tenant-a"
    assert principal.roles == (Role.OPERATOR,)

    assert service.revoke_service_key(tenant_id="tenant-a", key_id=record.key_id) is True
    with pytest.raises(InvalidCredentialError):
        service.authenticate_service_key(secret)


def test_service_key_expiry_must_be_one_to_ninety_days(tmp_path: Path) -> None:
    """Service key expiry outside 1-90 days is rejected."""
    service = auth_service_for(tmp_path)
    with pytest.raises(ValueError):
        service.create_service_key(
            tenant_id="tenant-a",
            subject="ci",
            roles=(Role.OPERATOR,),
            scopes=frozenset(),
            expires_at=utcnow() + timedelta(hours=1),
        )
    with pytest.raises(ValueError):
        service.create_service_key(
            tenant_id="tenant-a",
            subject="ci",
            roles=(Role.OPERATOR,),
            scopes=frozenset(),
            expires_at=utcnow() + timedelta(days=91),
        )


def test_service_key_scopes_cannot_exceed_role_grant(tmp_path: Path) -> None:
    """A service key cannot assert a scope its role does not grant."""
    service = auth_service_for(tmp_path)
    with pytest.raises(ValueError):
        service.create_service_key(
            tenant_id="tenant-a",
            subject="ci",
            roles=(Role.VIEWER,),
            scopes=frozenset({"run:write"}),
            expires_at=utcnow() + timedelta(days=30),
        )


def test_list_service_keys_never_returns_a_secret(tmp_path: Path) -> None:
    """Listing credentials exposes only metadata, never a secret or its hash's value."""
    service = auth_service_for(tmp_path)
    record, secret = service.create_service_key(
        tenant_id="tenant-a",
        subject="ci",
        roles=(Role.OPERATOR,),
        scopes=frozenset(),
        expires_at=utcnow() + timedelta(days=30),
    )
    listed = service.list_service_keys(tenant_id="tenant-a")
    assert [item.key_id for item in listed] == [record.key_id]
    for field_name in ("__dict__",):
        rendered = repr(listed[0])
        assert secret not in rendered


def test_session_round_trips_and_revokes(tmp_path: Path) -> None:
    """A created session authenticates, then stops authenticating once revoked."""
    service = auth_service_for(tmp_path)
    record = service.create_session(
        tenant_id="tenant-a",
        subject="user-1",
        roles=(Role.MAINTAINER,),
        refresh_token="raw-refresh-token",
    )
    principal = service.authenticate_session(record.session_id)
    assert principal.tenant_id == "tenant-a"
    assert principal.roles == (Role.MAINTAINER,)

    decrypted = service.decrypt_session_refresh_token(record)
    assert decrypted == "raw-refresh-token"

    db_text = (tmp_path / "auth.db").read_bytes()
    assert b"raw-refresh-token" not in db_text

    assert service.revoke_session(record.session_id) is True
    with pytest.raises(InvalidCredentialError):
        service.authenticate_session(record.session_id)


def test_authenticate_request_prefers_service_key_over_legacy_pat(tmp_path: Path) -> None:
    """A presented service key authenticates even when a legacy PAT is also configured."""
    import anyio
    from starlette.requests import Request

    settings = local_settings(autodev_api_token="legacy-token")
    service = auth_service_for(tmp_path, settings=settings)
    record, secret = service.create_service_key(
        tenant_id="tenant-a",
        subject="ci",
        roles=(Role.OPERATOR,),
        scopes=frozenset(),
        expires_at=utcnow() + timedelta(days=30),
    )

    async def _run() -> None:
        scope = {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {secret}".encode())],
        }
        request = Request(scope)
        principal = await service.authenticate_request(request)
        assert principal.auth_method.value == "service_key"
        assert principal.credential_id == record.key_id

    anyio.run(_run)
