"""Contract tests for ``/v2/quotas`` (E11-S3, ADR-019).

Mirrors ``backend/tests/integration/tenancy/test_cross_tenant_isolation.py``'s
fixture: a real ASGI app, real service-key auth, two distinct tenants.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from backend.auth.roles import Role
from backend.auth.service import get_auth_service, reset_auth_service_cache
from backend.auth.store import utcnow
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """A TestClient on an isolated temp SQLite store with real auth enforcement."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'quotas-api.db'}")
    monkeypatch.setenv("AUTODEV_API_TOKEN", "")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    reset_settings_cache()
    reset_store_cache()
    reset_auth_service_cache()
    from backend.api.main import app  # noqa: PLC0415

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_settings_cache()
    reset_store_cache()
    reset_auth_service_cache()


def _bearer(tenant_id: str, subject: str, *, roles: tuple[Role, ...] = (Role.ADMIN,)) -> dict[str, str]:
    """Mint a real, durably-issued service-key token for *tenant_id*."""
    service = get_auth_service()
    _record, token = service.create_service_key(
        tenant_id=tenant_id,
        subject=subject,
        roles=roles,
        scopes=frozenset(),
        expires_at=utcnow() + timedelta(days=1),
    )
    return {"Authorization": f"Bearer {token}"}


def _default_run_budget() -> dict:
    return {
        "maxTokens": 500_000,
        "maxCostMicrousd": 5_000_000,
        "maxWallClockMs": 600_000,
        "maxSteps": 200,
    }


def _policy_body(**overrides: object) -> dict:
    body = {
        "maxConcurrentRuns": 3,
        "maxStorageBytes": 10_000_000,
        "monthlyTokenLimit": 1_000_000,
        "monthlyCostMicrousd": 10_000_000,
        "requestsPerSecond": 5,
        "defaultRunBudget": _default_run_budget(),
    }
    body.update(overrides)
    return body


class TestGetUsage:
    def test_local_default_usage_before_any_policy_is_set(self, client: TestClient) -> None:
        headers = _bearer("tenant-a", "user-a", roles=(Role.VIEWER,))
        response = client.get("/v2/quotas/usage", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["concurrentRuns"] == 0
        assert body["storageBytesUsed"] == 0
        assert body["policy"]["maxConcurrentRuns"] > 0

    def test_requires_quota_read_scope(self, client: TestClient) -> None:
        headers = _bearer("tenant-a", "user-a", roles=())
        response = client.get("/v2/quotas/usage", headers=headers)
        assert response.status_code == 403


class TestSetPolicy:
    def test_admin_can_set_and_read_back_policy(self, client: TestClient) -> None:
        headers = _bearer("tenant-a", "admin-a", roles=(Role.ADMIN,))
        response = client.put("/v2/quotas/policy", headers=headers, json=_policy_body())
        assert response.status_code == 200
        body = response.json()
        assert body["maxConcurrentRuns"] == 3
        assert body["version"] == 1

        fetched = client.get("/v2/quotas/policy", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["maxConcurrentRuns"] == 3

    def test_viewer_cannot_set_policy(self, client: TestClient) -> None:
        headers = _bearer("tenant-a", "user-a", roles=(Role.VIEWER,))
        response = client.put("/v2/quotas/policy", headers=headers, json=_policy_body())
        assert response.status_code == 403

    def test_stale_expected_version_is_rejected(self, client: TestClient) -> None:
        headers = _bearer("tenant-a", "admin-a", roles=(Role.ADMIN,))
        first = client.put("/v2/quotas/policy", headers=headers, json=_policy_body())
        assert first.status_code == 200
        assert first.json()["version"] == 1

        second = client.put(
            "/v2/quotas/policy",
            headers=headers,
            json=_policy_body(maxConcurrentRuns=5) | {"expectedVersion": 1},
        )
        assert second.status_code == 200
        assert second.json()["version"] == 2

        # Stored version is now 2; a write still targeting 1 must 409.
        conflicting = client.put(
            "/v2/quotas/policy",
            headers=headers,
            json=_policy_body(maxConcurrentRuns=9) | {"expectedVersion": 1},
        )
        assert conflicting.status_code == 409


class TestQuotaTenantIsolation:
    def test_tenant_b_cannot_read_tenant_a_usage_or_policy(self, client: TestClient) -> None:
        headers_a = _bearer("tenant-a", "admin-a", roles=(Role.ADMIN,))
        headers_b = _bearer("tenant-b", "admin-b", roles=(Role.ADMIN,))

        set_response = client.put("/v2/quotas/policy", headers=headers_a, json=_policy_body(maxConcurrentRuns=7))
        assert set_response.status_code == 200

        # Tenant B has no such policy and no way to name tenant A's --
        # every request is implicitly scoped to the caller's own tenant.
        b_policy = client.get("/v2/quotas/policy", headers=headers_b)
        assert b_policy.status_code == 200
        assert b_policy.json()["maxConcurrentRuns"] != 7
