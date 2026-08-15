"""Contracts for the ``/v2/auth`` Control Plane surface (E11-S2 Task 2)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from backend.auth.service import reset_auth_service_cache
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient bound to a fresh SQLite-backed Auth Store per test."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth_api.db'}")
    monkeypatch.setenv("AUTODEV_API_TOKEN", "")
    reset_settings_cache()
    reset_store_cache()
    reset_auth_service_cache()
    from backend.api.main import app  # noqa: PLC0415

    with TestClient(app) as test_client:
        yield test_client
    reset_settings_cache()
    reset_store_cache()
    reset_auth_service_cache()


def test_me_is_open_in_local_zero_config(client: TestClient) -> None:
    """With no token/OIDC configured, /v2/auth/me resolves the local owner principal."""
    response = client.get("/v2/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "local"
    assert body["tenantId"] == "default"
    assert "owner" in body["roles"]
    assert body["authMethod"] == "local"


def test_legacy_pat_authenticates_as_admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy compatibility PAT authenticates as an admin-equivalent principal."""
    monkeypatch.setenv("AUTODEV_API_TOKEN", "legacy-token")
    reset_settings_cache()
    reset_store_cache()
    reset_auth_service_cache()
    response = client.get(
        "/v2/auth/me", headers={"Authorization": "Bearer legacy-token"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["authMethod"] == "legacy_pat"
    assert body["roles"] == ["admin"]


def test_service_credential_lifecycle(client: TestClient) -> None:
    """Create, use, list, and revoke a service credential end to end."""
    create = client.post(
        "/v2/auth/service-credentials",
        json={
            "subject": "ci",
            "roles": ["operator"],
            "scopes": [],
            "expiresInDays": 30,
        },
    )
    assert create.status_code == 201
    body = create.json()
    key = body["key"]
    assert key.startswith("adk_live_")

    listed = client.get("/v2/auth/service-credentials")
    assert listed.status_code == 200
    assert all(item.get("key") is None for item in listed.json())

    authenticated = client.get("/v2/auth/me", headers={"Authorization": f"Bearer {key}"})
    assert authenticated.status_code == 200
    assert authenticated.json()["authMethod"] == "service_key"
    assert authenticated.json()["roles"] == ["operator"]

    revoked = client.delete(f"/v2/auth/service-credentials/{body['keyId']}")
    assert revoked.status_code == 204

    after_revoke = client.get("/v2/auth/me", headers={"Authorization": f"Bearer {key}"})
    assert after_revoke.status_code == 401


def test_service_credential_scopes_exceeding_role_are_rejected(client: TestClient) -> None:
    """A service-credential request cannot assert a scope its role does not grant."""
    response = client.post(
        "/v2/auth/service-credentials",
        json={
            "subject": "ci",
            "roles": ["viewer"],
            "scopes": ["run:write"],
            "expiresInDays": 30,
        },
    )
    assert response.status_code == 400


def test_oidc_login_404s_when_not_configured(client: TestClient) -> None:
    """Starting an OIDC login without provider configuration is a 404, not a crash."""
    response = client.get("/v2/auth/oidc/login", follow_redirects=False)
    assert response.status_code == 404


def test_oidc_pkce_login_sets_httponly_secure_session_cookie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed PKCE login sets an HttpOnly, Secure session cookie and encrypts the refresh token."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth_api_oidc.db'}")
    monkeypatch.setenv("AUTODEV_OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setenv("AUTODEV_OIDC_AUDIENCE", "autodev")
    monkeypatch.setenv("AUTODEV_OIDC_JWKS_URL", "https://idp.example.com/jwks.json")
    monkeypatch.setenv("AUTODEV_OIDC_AUTHORIZATION_URL", "https://idp.example.com/authorize")
    monkeypatch.setenv("AUTODEV_OIDC_TOKEN_URL", "https://idp.example.com/token")
    monkeypatch.setenv("AUTODEV_OIDC_CLIENT_ID", "autodev-backend")
    reset_settings_cache()
    reset_store_cache()
    reset_auth_service_cache()

    import backend.api.routers.auth_v2 as auth_v2_module
    from backend.auth.contracts import AuthMethod, PrincipalV2, Role
    from backend.auth.service import AuthService

    async def _fake_exchange(*_args: object, **_kwargs: object) -> dict[str, str]:
        return {"id_token": "fake-id-token", "refresh_token": "raw-refresh-token"}

    def _fake_authenticate_oidc_bearer(self: AuthService, token: str) -> PrincipalV2:
        del self, token
        return PrincipalV2(
            subject="user-1",
            tenant_id="tenant-a",
            roles=(Role.MAINTAINER,),
            scopes=frozenset(),
            auth_method=AuthMethod.OIDC,
        )

    monkeypatch.setattr(auth_v2_module, "exchange_code_for_tokens", _fake_exchange)
    monkeypatch.setattr(AuthService, "authenticate_oidc_bearer", _fake_authenticate_oidc_bearer)

    from backend.api.main import app  # noqa: PLC0415

    with TestClient(app) as test_client:
        login = test_client.get("/v2/auth/oidc/login?returnTo=/dashboard", follow_redirects=False)
        assert login.status_code == 302
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]

        callback = test_client.get(
            f"/v2/auth/oidc/callback?code=abc&state={state}", follow_redirects=False
        )
        assert callback.status_code == 302
        assert callback.headers["location"] == "/dashboard"
        set_cookie = callback.headers["set-cookie"]
        assert "autodev_session=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie

        db_text = (tmp_path / "auth_api_oidc.db").read_bytes()
        assert b"raw-refresh-token" not in db_text

    reset_settings_cache()
    reset_store_cache()
    reset_auth_service_cache()


def test_oidc_callback_rejects_unknown_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A callback whose state does not match a pending login is rejected."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth_api_oidc2.db'}")
    monkeypatch.setenv("AUTODEV_OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setenv("AUTODEV_OIDC_AUDIENCE", "autodev")
    monkeypatch.setenv("AUTODEV_OIDC_JWKS_URL", "https://idp.example.com/jwks.json")
    monkeypatch.setenv("AUTODEV_OIDC_AUTHORIZATION_URL", "https://idp.example.com/authorize")
    monkeypatch.setenv("AUTODEV_OIDC_TOKEN_URL", "https://idp.example.com/token")
    monkeypatch.setenv("AUTODEV_OIDC_CLIENT_ID", "autodev-backend")
    reset_settings_cache()
    reset_store_cache()
    reset_auth_service_cache()

    from backend.api.main import app  # noqa: PLC0415

    with TestClient(app) as test_client:
        response = test_client.get(
            "/v2/auth/oidc/callback?code=abc&state=never-issued", follow_redirects=False
        )
        assert response.status_code == 400

    reset_settings_cache()
    reset_store_cache()
    reset_auth_service_cache()
