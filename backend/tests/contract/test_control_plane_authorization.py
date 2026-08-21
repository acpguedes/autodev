"""Executable authorization-coverage contract for the Control Plane (E11-S2 Task 3).

This is the guardrail ADR-018 relies on in place of enforcing the
fail-closed unannotated-route policy in every profile: any new
Control-Plane route that ships without a declared
``@requires_scope``/``@public_endpoint`` marker fails this test, in local
dev and in CI, long before it could reach production.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.authorization import protected_routes_without_requirement
from backend.auth.roles import Role
from backend.auth.service import get_auth_service, reset_auth_service_cache
from backend.auth.store import utcnow
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient bound to a fresh SQLite-backed Auth Store per test."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'contract.db'}")
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


def test_every_non_public_route_declares_policy(client: TestClient) -> None:
    """Every route owned by a Control Plane router declares a scope or is public."""
    from backend.api.main import app  # noqa: PLC0415

    missing = protected_routes_without_requirement(app)
    assert missing == []


def test_service_credentials_are_isolated_by_tenant(client: TestClient) -> None:
    """A caller's own tenant is the only tenant it can see or manage credentials for.

    Tenant is always derived from the authenticated principal — no request
    body, query parameter, or header can select a different tenant.
    """
    service = get_auth_service()
    _record_a, token_a = service.create_service_key(
        tenant_id="tenant-a",
        subject="admin-a",
        roles=(Role.ADMIN,),
        scopes=frozenset(),
        expires_at=utcnow() + timedelta(days=1),
    )
    _record_b, token_b = service.create_service_key(
        tenant_id="tenant-b",
        subject="admin-b",
        roles=(Role.ADMIN,),
        scopes=frozenset(),
        expires_at=utcnow() + timedelta(days=1),
    )

    created = client.post(
        "/v2/auth/service-credentials",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"subject": "ci-a", "roles": ["operator"], "scopes": [], "expiresInDays": 30},
    )
    assert created.status_code == 201
    key_id = created.json()["keyId"]

    listed_by_b = client.get(
        "/v2/auth/service-credentials", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert listed_by_b.status_code == 200
    assert key_id not in {item["keyId"] for item in listed_by_b.json()}

    revoke_from_b = client.delete(
        f"/v2/auth/service-credentials/{key_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert revoke_from_b.status_code == 404

    listed_by_a = client.get(
        "/v2/auth/service-credentials", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert key_id in {item["keyId"] for item in listed_by_a.json()}


def test_local_owner_principal_can_use_every_execution_endpoint(client: TestClient) -> None:
    """The local zero-config principal never 403s on an audited Execution endpoint (E42-S2).

    Regression for the ``policy:read``/``policy:admin`` gap: both scopes
    were required by ``/v2/execution/policy*`` but never defined in
    ``backend.auth.roles.ROLE_GRANTS``, so even ``Role.OWNER`` -- the local
    zero-config principal's role -- could never call them. Exercises every
    ``@requires_scope``-gated endpoint under ``/v2/execution/*`` and
    ``/v2/runs/*`` (E42-S2-T1's audit scope) with no ``Authorization``
    header, i.e. as the local zero-config ``Role.OWNER`` principal.
    """
    listed = client.get("/v2/execution/policy")
    assert listed.status_code == 200, listed.text

    added = client.post(
        "/v2/execution/policy",
        json={
            "category": "shell",
            "effect": "allow",
            "scopeKind": "project",
            "scopeId": "default",
        },
    )
    assert added.status_code == 201, added.text

    dynamic = client.get("/v2/execution/policy/dynamic")
    assert dynamic.status_code == 200, dynamic.text

    decisions = client.get("/v2/execution/decisions")
    assert decisions.status_code == 200, decisions.text


def test_session_actor_is_derived_from_principal_not_request_body(client: TestClient) -> None:
    """A created session's plan is derived from the caller, not a spoofable field.

    ``SessionCreateRequestV2`` accepts only ``goal`` — there is no ``actor``
    or ``subject`` field a caller could set to impersonate another
    principal, which is the structural guarantee behind "derive actor from
    the authenticated principal" for this resource.
    """
    service = get_auth_service()
    _record, token = service.create_service_key(
        tenant_id="tenant-a",
        subject="real-caller",
        roles=(Role.OPERATOR,),
        scopes=frozenset(),
        expires_at=utcnow() + timedelta(days=1),
    )
    response = client.post(
        "/v2/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"goal": "ship", "actor": "someone-else", "subject": "someone-else"},
    )
    assert response.status_code == 201
    assert "actor" not in response.json()
    assert "subject" not in response.json()
