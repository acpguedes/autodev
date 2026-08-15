"""Contracts for required access/denial audit persistence (E11-S2 Task 4)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.auth.audit import AuditWriter, override_audit_writer
from backend.auth.contracts import AccessAuditRecord, AuthMethod, Role
from backend.auth.service import get_auth_service, reset_auth_service_cache
from backend.auth.store import AuthStore, utcnow
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache
from backend.persistence.sqlite_adapter import SQLiteStore


class FailingAuditWriter(AuditWriter):
    """An audit writer that always fails to persist — for RED verification."""

    def __init__(self) -> None:  # noqa: D107 - intentionally skips AuditWriter's store setup
        pass

    def record(self, record: AccessAuditRecord, *, required: bool) -> None:
        raise RuntimeError("audit store unavailable")

    def list(
        self, *, tenant_id: str, limit: int, before: datetime | None
    ) -> list[AccessAuditRecord]:
        return []


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient bound to a fresh SQLite-backed Auth Store per test."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'audit.db'}")
    monkeypatch.setenv("AUTODEV_API_TOKEN", "")
    reset_settings_cache()
    reset_store_cache()
    reset_auth_service_cache()
    override_audit_writer(None)
    from backend.api.main import app  # noqa: PLC0415

    with TestClient(app) as test_client:
        yield test_client
    override_audit_writer(None)
    reset_settings_cache()
    reset_store_cache()
    reset_auth_service_cache()


def _viewer_token(*, tenant_id: str = "tenant-a") -> str:
    service = get_auth_service()
    _record, key = service.create_service_key(
        tenant_id=tenant_id,
        subject="test-caller",
        roles=(Role.VIEWER,),
        scopes=frozenset(),
        expires_at=utcnow() + timedelta(days=1),
    )
    return key


def _admin_token(*, tenant_id: str = "tenant-a") -> str:
    service = get_auth_service()
    _record, key = service.create_service_key(
        tenant_id=tenant_id,
        subject="admin-caller",
        roles=(Role.ADMIN,),
        scopes=frozenset(),
        expires_at=utcnow() + timedelta(days=1),
    )
    return key


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_allowed_and_denied_decisions_are_durable(client: TestClient) -> None:
    """A GET (allowed) and a POST (denied) both leave a durable audit row."""
    viewer = _viewer_token()
    admin = _admin_token()

    assert client.get("/v2/sessions", headers=_bearer(viewer)).status_code == 200
    assert (
        client.post("/v2/sessions", headers=_bearer(viewer), json={"goal": "x"}).status_code
        == 403
    )

    response = client.get("/v2/audit/access", headers=_bearer(admin))
    assert response.status_code == 200
    items = response.json()["items"]
    decisions = [item["decision"] for item in items]
    assert "allowed" in decisions
    assert "denied" in decisions


def test_required_audit_failure_blocks_allowed_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A required-audit write failure denies an otherwise-allowed request."""
    override_audit_writer(FailingAuditWriter())
    viewer = _viewer_token()
    response = client.get("/v2/sessions", headers=_bearer(viewer))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "security.audit_unavailable"


def test_denial_stands_even_if_audit_write_fails(client: TestClient) -> None:
    """A required-audit write failure does not turn a denial into an allow."""
    override_audit_writer(FailingAuditWriter())
    viewer = _viewer_token()
    response = client.post("/v2/sessions", headers=_bearer(viewer), json={"goal": "x"})
    assert response.status_code == 403


def test_audit_rows_never_contain_credentials_or_bodies(client: TestClient) -> None:
    """Audit rows carry only stable identifiers, never the presented secret or a body."""
    viewer = _viewer_token()
    admin = _admin_token()
    secret_goal = "do-not-audit-this-request-body-value"

    client.get("/v2/sessions", headers=_bearer(viewer))
    client.post("/v2/sessions", headers=_bearer(viewer), json={"goal": secret_goal})

    response = client.get("/v2/audit/access", headers=_bearer(admin))
    rendered = response.text
    assert viewer not in rendered
    assert secret_goal not in rendered


def test_audit_retrieval_is_tenant_scoped(client: TestClient) -> None:
    """A caller only ever sees their own tenant's audit rows."""
    viewer_a = _viewer_token(tenant_id="tenant-a")
    admin_a = _admin_token(tenant_id="tenant-a")
    admin_b = _admin_token(tenant_id="tenant-b")

    client.get("/v2/sessions", headers=_bearer(viewer_a))

    from_a = client.get("/v2/audit/access", headers=_bearer(admin_a))
    assert from_a.status_code == 200
    assert len(from_a.json()["items"]) >= 1

    # tenant-b's own admin-read of the audit trail is itself an audited
    # "allowed" row for tenant-b — the isolation guarantee is that none of
    # tenant-a's rows (viewer_a's GET) ever appear in tenant-b's listing.
    from_b = client.get("/v2/audit/access", headers=_bearer(admin_b))
    assert from_b.status_code == 200
    assert all(item["subject"] != "test-caller" for item in from_b.json()["items"])


def test_audit_read_requires_audit_read_scope(client: TestClient) -> None:
    """A viewer cannot read the audit trail — audit:read is an admin-tier scope."""
    viewer = _viewer_token()
    response = client.get("/v2/audit/access", headers=_bearer(viewer))
    assert response.status_code == 403


def test_store_append_and_list_round_trip(tmp_path: Path) -> None:
    """AuthStore persists and retrieves access-audit rows directly."""
    store = AuthStore(SQLiteStore(f"sqlite:///{tmp_path / 'direct.db'}"))
    record = AccessAuditRecord(
        audit_id="a1",
        occurred_at=utcnow(),
        tenant_id="tenant-a",
        subject="user-1",
        auth_method=AuthMethod.SERVICE_KEY,
        credential_id="key-1",
        roles=(Role.VIEWER,),
        required_scope="session:read",
        resource_type="sessions",
        resource_id=None,
        method="GET",
        route_template="/v2/sessions",
        decision="allowed",
        reason="ok",
        request_id="req-1",
    )
    writer = AuditWriter(store)
    writer.record(record, required=True)
    rows = writer.list(tenant_id="tenant-a", limit=10, before=None)
    assert len(rows) == 1
    assert rows[0].audit_id == "a1"
    assert rows[0].decision == "allowed"
