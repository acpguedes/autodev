"""Contracts for Control Plane RBAC enforcement (E11-S2 Task 3)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.api.authorization import enforce_control_plane_access
from backend.auth.roles import Role
from backend.auth.service import get_auth_service, reset_auth_service_cache
from backend.auth.store import utcnow
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient bound to a fresh SQLite-backed Auth Store per test."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'rbac.db'}")
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


def viewer_token(*, tenant_id: str = "tenant-a") -> str:
    """Mint a short-lived service key authenticating as ``viewer``."""
    return _token_for(Role.VIEWER, tenant_id=tenant_id)


def _token_for(role: Role, *, tenant_id: str = "tenant-a") -> str:
    """Mint a short-lived service key authenticating as ``role``."""
    service = get_auth_service()
    _record, key = service.create_service_key(
        tenant_id=tenant_id,
        subject="test-caller",
        roles=(role,),
        scopes=frozenset(),
        expires_at=utcnow() + timedelta(days=1),
    )
    return key


def bearer_header(token: str) -> dict[str, str]:
    """Build an ``Authorization: Bearer`` header."""
    return {"Authorization": f"Bearer {token}"}


def test_viewer_cannot_create_session(client: TestClient) -> None:
    """A viewer-role caller is denied a write action with a scope-missing 403."""
    response = client.post(
        "/v2/sessions",
        headers=bearer_header(viewer_token()),
        json={"goal": "change code"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "authorization.scope_missing"


def test_viewer_can_list_sessions(client: TestClient) -> None:
    """A viewer-role caller can perform a declared read action."""
    response = client.get("/v2/sessions", headers=bearer_header(viewer_token()))
    assert response.status_code == 200


def test_missing_credentials_return_401(client: TestClient) -> None:
    """An unrecognized bearer credential on a protected route is a 401."""
    response = client.get("/v2/sessions", headers=bearer_header("garbage-token"))
    assert response.status_code == 401


def test_operator_can_start_but_not_admin_plugins(client: TestClient) -> None:
    """Role tiers compose: operator can write sessions but not admin plugins."""
    token = _token_for(Role.OPERATOR)
    created = client.post("/v2/sessions", headers=bearer_header(token), json={"goal": "ship"})
    assert created.status_code == 201
    forbidden = client.post(
        "/v2/extensions/agent/acme.example/enable", headers=bearer_header(token)
    )
    assert forbidden.status_code == 403


def _prod_app_with_unannotated_route(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Build a minimal app, in production mode, with one deliberately unannotated route."""
    import backend.api.authorization as authorization_module
    from backend.config.settings import Settings

    prod_settings = Settings.model_construct(autodev_profile="prod", autodev_api_token="")
    monkeypatch.setattr(authorization_module, "Settings", lambda: prod_settings)

    app = FastAPI(dependencies=[Depends(enforce_control_plane_access)])

    @app.get("/v2/plugin-route")
    def unannotated_route() -> dict[str, str]:
        return {"ok": "true"}

    return app


def test_unannotated_dynamic_route_fails_closed_in_production(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unannotated route (e.g. from a naive plugin router) is denied in production."""
    token = viewer_token()
    prod_app = _prod_app_with_unannotated_route(monkeypatch)
    response = TestClient(prod_app).get("/v2/plugin-route", headers=bearer_header(token))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "authorization.policy_missing"
