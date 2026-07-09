"""Contract tests for the ``/v2/plans`` step-approval API (E16-S2-T6).

Exercises the full step lifecycle (``draft -> under_review -> approved |
rejected -> executing -> completed``): every legal transition, an illegal
transition (executing a not-yet-approved step), the approve-then-execute
happy path, ``schemaVersion`` presence on every response, and that each
transition emits a validated ``plan.step.*`` event on the E9-S3 bus.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.events.runtime import get_event_bus, reset_event_bus_for_tests
from backend.llm.factory import get_chat_model
from backend.persistence.database import reset_store_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """A TestClient on an isolated temp SQLite store with a fresh event bus.

    Mirrors ``backend/tests/test_v2_api_contract.py``'s isolation, plus an
    event-bus reset since :func:`backend.events.runtime.get_event_bus` is a
    process-wide singleton that must not leak state between tests.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'v2-plan-approval.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # ``backend.api.main`` calls ``load_dotenv(override=True)`` at import time.
    # Inside a git worktree, python-dotenv's upward search escapes the
    # worktree and loads the main checkout's real ``.env`` (which pins
    # ``LLM_PROVIDER=openai`` without an API key), clobbering the isolation
    # above. Neutralize that one-time import side effect for this test
    # process; it is unrelated to app behavior under test.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    reset_runtime_config_cache()
    reset_settings_cache()
    reset_store_cache()
    reset_event_bus_for_tests()
    get_chat_model.cache_clear()
    from backend.api.main import app

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_store_cache()
    reset_runtime_config_cache()
    reset_event_bus_for_tests()
    get_chat_model.cache_clear()


def _seed_plan(client: TestClient, session_id: str, steps: list[str]) -> None:
    """Create a legacy plan document so the ``/v2`` steps have content to seed from."""
    response = client.put(f"/plans/{session_id}", json={"steps": steps})
    assert response.status_code == 200, response.text


class TestPlanReadAndEdit:
    """T1: list steps, read a single step, edit content prior to approval."""

    def test_get_plan_lists_steps_with_schema_version(self, client: TestClient) -> None:
        _seed_plan(client, "s1", ["Write the migration", "Run the migration"])
        response = client.get("/v2/plans/s1")
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["session_id"] == "s1"
        assert len(body["steps"]) == 2
        assert body["steps"][0]["content"] == "Write the migration"
        # Steps are auto-promoted out of draft on first read.
        assert body["steps"][0]["state"] == "under_review"
        assert body["status"] == "under_review"

    def test_get_plan_unknown_session_returns_404(self, client: TestClient) -> None:
        response = client.get("/v2/plans/no-such-session")
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["schemaVersion"] == "2.0"
        assert detail["error"]["code"] == 404

    def test_get_single_step(self, client: TestClient) -> None:
        _seed_plan(client, "s2", ["Step A", "Step B"])
        response = client.get("/v2/plans/s2/steps/1")
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["step_index"] == 1
        assert body["content"] == "Step B"

    def test_get_unknown_step_returns_404(self, client: TestClient) -> None:
        _seed_plan(client, "s3", ["Only step"])
        response = client.get("/v2/plans/s3/steps/5")
        assert response.status_code == 404

    def test_edit_step_content_before_approval(self, client: TestClient) -> None:
        _seed_plan(client, "s4", ["Original content"])
        response = client.put("/v2/plans/s4/steps/0", json={"content": "Revised content"})
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["content"] == "Revised content"
        assert body["state"] == "under_review"

    def test_edit_step_content_after_approval_is_denied(self, client: TestClient) -> None:
        _seed_plan(client, "s5", ["Step to approve"])
        approve = client.post("/v2/plans/s5/steps/0/approve", json={"actor": "alice"})
        assert approve.status_code == 200
        response = client.put("/v2/plans/s5/steps/0", json={"content": "Too late"})
        assert response.status_code == 400
        assert response.json()["detail"]["schemaVersion"] == "2.0"


class TestApprovalAndExecution:
    """T2: approve/reject a step, then execute only approved steps."""

    def test_approve_step_transitions_and_stamps_schema_version(self, client: TestClient) -> None:
        _seed_plan(client, "s6", ["Step to approve"])
        response = client.post("/v2/plans/s6/steps/0/approve", json={"actor": "alice"})
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["state"] == "approved"

    def test_reject_step_transitions(self, client: TestClient) -> None:
        _seed_plan(client, "s7", ["Step to reject"])
        response = client.post("/v2/plans/s7/steps/0/reject", json={"actor": "bob", "note": "not needed"})
        assert response.status_code == 200
        assert response.json()["state"] == "rejected"

    def test_approve_then_execute_approved_happy_path(self, client: TestClient) -> None:
        _seed_plan(client, "s8", ["Step one", "Step two"])
        client.post("/v2/plans/s8/steps/0/approve", json={"actor": "alice"})
        client.post("/v2/plans/s8/steps/1/approve", json={"actor": "alice"})
        response = client.post("/v2/plans/s8/execute-approved", json={"actor": "alice"})
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["status"] == "completed"
        assert all(step["state"] == "completed" for step in body["steps"])

    def test_execute_approved_with_no_approved_steps_returns_400(self, client: TestClient) -> None:
        _seed_plan(client, "s9", ["Untouched step"])
        response = client.post("/v2/plans/s9/execute-approved", json={})
        assert response.status_code == 400
        assert response.json()["detail"]["schemaVersion"] == "2.0"

    def test_execute_named_rejected_step_is_denied(self, client: TestClient) -> None:
        """Illegal transition: executing a rejected step must be refused (T2)."""
        _seed_plan(client, "s10", ["Step to reject"])
        client.post("/v2/plans/s10/steps/0/reject", json={"actor": "bob"})
        response = client.post("/v2/plans/s10/execute-approved", json={"step_indices": [0]})
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["schemaVersion"] == "2.0"
        assert detail["error"]["code"] == 400

    def test_execute_named_pending_step_is_denied(self, client: TestClient) -> None:
        """Illegal transition: executing a still-under-review step must be refused (T2)."""
        _seed_plan(client, "s11", ["Untouched step"])
        client.get("/v2/plans/s11")  # auto-promote to under_review
        response = client.post("/v2/plans/s11/execute-approved", json={"step_indices": [0]})
        assert response.status_code == 400


class TestStateMachine:
    """T3: illegal transitions are denied and every transition emits an event."""

    def test_reject_after_approve_is_illegal(self, client: TestClient) -> None:
        _seed_plan(client, "s12", ["Step"])
        client.post("/v2/plans/s12/steps/0/approve", json={"actor": "alice"})
        response = client.post("/v2/plans/s12/steps/0/reject", json={"actor": "bob"})
        assert response.status_code == 400
        assert response.json()["detail"]["error"]["code"] == 400

    def test_approve_after_reject_is_illegal(self, client: TestClient) -> None:
        _seed_plan(client, "s13", ["Step"])
        client.post("/v2/plans/s13/steps/0/reject", json={"actor": "bob"})
        response = client.post("/v2/plans/s13/steps/0/approve", json={"actor": "alice"})
        assert response.status_code == 400

    def test_transitions_emit_validated_plan_step_events(self, client: TestClient) -> None:
        _seed_plan(client, "s14", ["Step"])
        client.get("/v2/plans/s14")  # draft -> under_review
        client.post("/v2/plans/s14/steps/0/approve", json={"actor": "alice"})  # under_review -> approved
        client.post("/v2/plans/s14/execute-approved", json={"actor": "alice"})  # approved -> executing -> completed

        envelopes = get_event_bus().replay("s14")
        types = [envelope.type for envelope in envelopes]
        assert types == [
            "plan.step.reviewing",
            "plan.step.approved",
            "plan.step.executing",
            "plan.step.completed",
        ]
        for envelope in envelopes:
            assert envelope.schemaVersion
            assert envelope.tenantId == "default"
            assert envelope.partitionKey == "s14"
            assert envelope.data["sessionId"] == "s14"
            assert envelope.data["stepIndex"] == 0
        for envelope in envelopes[1:]:
            assert envelope.data["actor"] == "alice"
        assert envelopes[0].data == {
            "sessionId": "s14",
            "stepIndex": 0,
            "fromState": "draft",
            "toState": "under_review",
            "actor": "system",
        }
        assert envelopes[1].data["fromState"] == "under_review"
        assert envelopes[1].data["toState"] == "approved"
