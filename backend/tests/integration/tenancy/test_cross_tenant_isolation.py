"""Cross-tenant isolation contract for the Control Plane API (E11-S3, ADR-019).

Every check here drives the real ASGI app end to end with two distinct,
durably-issued service-key principals (``tenant-a``/``tenant-b``) — never a
mocked principal or a direct repository call — and proves tenant B cannot
observe or mutate tenant A's sessions, flow runs, plan approvals, or patch
reviews. A resource owned by the other tenant must be indistinguishable from
one that never existed (404, never 403), so as to not leak its existence
across a tenant boundary.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, Generator

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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'tenancy.db'}")
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


def _bearer(tenant_id: str, subject: str) -> dict[str, str]:
    """Mint a real, durably-issued admin service-key token for *tenant_id*.

    Args:
        tenant_id: Tenant the credential authenticates into.
        subject: Human-readable subject the credential is issued to.

    Returns:
        An ``Authorization`` header mapping using the raw bearer token.
    """
    service = get_auth_service()
    _record, token = service.create_service_key(
        tenant_id=tenant_id,
        subject=subject,
        roles=(Role.ADMIN,),
        scopes=frozenset(),
        expires_at=utcnow() + timedelta(days=1),
    )
    return {"Authorization": f"Bearer {token}"}


def _skill_flow(flow_id: str) -> dict[str, Any]:
    """A minimal single-skill flow manifest for the isolation flow tests."""
    return {
        "schemaVersion": "1",
        "id": flow_id,
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "nodes": [{"id": "only", "type": "skill", "ref": "autodev/skill-echo"}],
        "edges": [],
    }


def _register_echo_skill() -> None:
    """Register an in-process echo skill on the flows router's engine dependency."""
    from backend.api.main import app  # noqa: PLC0415
    from backend.api.routers import flows as flows_router  # noqa: PLC0415
    from backend.flows.engine import FlowEngine  # noqa: PLC0415
    from backend.flows.handlers import CallableRegistry, build_default_handlers  # noqa: PLC0415

    callables = CallableRegistry()
    callables.register("autodev/skill-echo", lambda payload: {"echo": payload})

    def engine_with_echo() -> FlowEngine:
        return FlowEngine(handlers=build_default_handlers(callables=callables))

    app.dependency_overrides[flows_router.get_flow_engine] = engine_with_echo


class TestSessionIsolation:
    """A session created by one tenant is invisible to another."""

    def test_tenant_b_cannot_read_tenant_a_session(self, client: TestClient) -> None:
        headers_a = _bearer("tenant-a", "user-a")
        headers_b = _bearer("tenant-b", "user-b")

        created = client.post("/v2/sessions", headers=headers_a, json={"goal": "ship it"})
        assert created.status_code == 201
        session_id = created.json()["session_id"]

        own_read = client.get(f"/v2/sessions/{session_id}", headers=headers_a)
        assert own_read.status_code == 200

        cross_read = client.get(f"/v2/sessions/{session_id}", headers=headers_b)
        assert cross_read.status_code == 404

    def test_tenant_b_session_listing_excludes_tenant_a(self, client: TestClient) -> None:
        headers_a = _bearer("tenant-a", "user-a")
        headers_b = _bearer("tenant-b", "user-b")

        created = client.post("/v2/sessions", headers=headers_a, json={"goal": "ship it"})
        session_id = created.json()["session_id"]

        listed_by_b = client.get("/v2/sessions", headers=headers_b)
        assert listed_by_b.status_code == 200
        assert session_id not in {item["session_id"] for item in listed_by_b.json()["items"]}

    def test_tenant_b_cannot_execute_tenant_a_execution_plan(self, client: TestClient) -> None:
        headers_a = _bearer("tenant-a", "user-a")
        headers_b = _bearer("tenant-b", "user-b")

        created = client.post("/v2/sessions", headers=headers_a, json={"goal": "ship it"})
        session_id = created.json()["session_id"]

        cross_plan = client.get(f"/v2/sessions/{session_id}/execution-plan", headers=headers_b)
        assert cross_plan.status_code == 404

        cross_execute = client.post(
            f"/v2/sessions/{session_id}/execution-plan/execute", headers=headers_b
        )
        assert cross_execute.status_code == 404


class TestFlowRunIsolation:
    """A flow run started by one tenant is invisible to another."""

    def test_tenant_b_cannot_read_tenant_a_run_or_its_events(self, client: TestClient) -> None:
        _register_echo_skill()
        headers_a = _bearer("tenant-a", "user-a")
        headers_b = _bearer("tenant-b", "user-b")

        registered = client.post(
            "/v2/flows", headers=headers_a, json=_skill_flow("autodev/flow-isolation-a")
        )
        assert registered.status_code == 201

        started = client.post(
            "/v2/flows/autodev/flow-isolation-a/runs", headers=headers_a, json={}
        )
        assert started.status_code == 201
        run_id = started.json()["runId"]

        own_read = client.get(f"/v2/flows/runs/{run_id}", headers=headers_a)
        assert own_read.status_code == 200

        cross_read = client.get(f"/v2/flows/runs/{run_id}", headers=headers_b)
        assert cross_read.status_code == 404

        cross_events = client.get(f"/v2/flows/runs/{run_id}/events", headers=headers_b)
        assert cross_events.status_code == 404

    def test_tenant_b_cannot_stream_tenant_a_run_events(self, client: TestClient) -> None:
        _register_echo_skill()
        headers_a = _bearer("tenant-a", "user-a")
        headers_b = _bearer("tenant-b", "user-b")

        registered = client.post(
            "/v2/flows", headers=headers_a, json=_skill_flow("autodev/flow-isolation-b")
        )
        assert registered.status_code == 201
        started = client.post(
            "/v2/flows/autodev/flow-isolation-b/runs", headers=headers_a, json={}
        )
        run_id = started.json()["runId"]

        cross_stream = client.get(
            f"/v2/runs/{run_id}/events/stream", headers=headers_b
        )
        assert cross_stream.status_code == 404

    def test_ignoring_a_client_supplied_tenant_id_on_start_run(self, client: TestClient) -> None:
        """A legacy ``tenantId`` body field can never assign a run to another tenant."""
        _register_echo_skill()
        headers_a = _bearer("tenant-a", "user-a")

        registered = client.post(
            "/v2/flows", headers=headers_a, json=_skill_flow("autodev/flow-isolation-c")
        )
        assert registered.status_code == 201

        started = client.post(
            "/v2/flows/autodev/flow-isolation-c/runs",
            headers=headers_a,
            json={"tenantId": "tenant-b"},
        )
        assert started.status_code == 201
        run_id = started.json()["runId"]

        # The run is owned by tenant-a (the authenticated caller), not the
        # spoofed body field: tenant-a can still read it back.
        own_read = client.get(f"/v2/flows/runs/{run_id}", headers=headers_a)
        assert own_read.status_code == 200


class TestPlanApprovalIsolation:
    """A session's plan-approval state is invisible to another tenant."""

    def test_tenant_b_cannot_read_or_mutate_tenant_a_plan(self, client: TestClient) -> None:
        headers_a = _bearer("tenant-a", "user-a")
        headers_b = _bearer("tenant-b", "user-b")

        session_id = "shared-looking-session-id"
        seed = client.put(f"/plans/{session_id}", headers=headers_a, json={"steps": ["Step A"]})
        assert seed.status_code == 200

        own_read = client.get(f"/v2/plans/{session_id}", headers=headers_a)
        assert own_read.status_code == 200

        cross_read = client.get(f"/v2/plans/{session_id}", headers=headers_b)
        assert cross_read.status_code == 404

        cross_approve = client.post(
            f"/v2/plans/{session_id}/steps/0/approve", headers=headers_b, json={}
        )
        assert cross_approve.status_code == 404

        cross_add = client.post(
            f"/v2/plans/{session_id}/steps",
            headers=headers_b,
            json={"content": "Injected by tenant-b"},
        )
        assert cross_add.status_code == 404


class TestPatchReviewIsolation:
    """A session's proposed patches are invisible to another tenant."""

    def test_tenant_b_cannot_list_or_read_tenant_a_patches(self, client: TestClient) -> None:
        headers_a = _bearer("tenant-a", "user-a")
        headers_b = _bearer("tenant-b", "user-b")

        session_id = "another-shared-looking-session-id"
        proposed = client.post(
            f"/v2/sessions/{session_id}/patches",
            headers=headers_a,
            json={"path": "a.py", "original": "x = 1\n", "updated": "x = 2\n"},
        )
        assert proposed.status_code == 201
        patch_id = proposed.json()["patch_id"]

        own_list = client.get(f"/v2/sessions/{session_id}/patches", headers=headers_a)
        assert own_list.status_code == 200
        assert len(own_list.json()["items"]) == 1

        cross_list = client.get(f"/v2/sessions/{session_id}/patches", headers=headers_b)
        assert cross_list.status_code == 200
        assert cross_list.json()["items"] == []

        cross_read = client.get(
            f"/v2/sessions/{session_id}/patches/{patch_id}", headers=headers_b
        )
        assert cross_read.status_code == 404

        cross_discard = client.post(
            f"/v2/sessions/{session_id}/patches/{patch_id}/discard", headers=headers_b
        )
        assert cross_discard.status_code == 404
