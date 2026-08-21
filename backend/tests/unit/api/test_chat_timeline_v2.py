"""E16-S1 contract tests for ``/v2`` turns and the timeline event taxonomy.

Exercises the turn endpoints (``backend/api/routers/chat_v2.py``) for: a
happy path per endpoint, the standardized validation-error shape,
``schemaVersion`` presence on every response, and pagination on the list
endpoint (mirroring ``backend/tests/test_v2_api_contract.py``). Also
validates that the new ``run.timeline.*`` event types
(``backend/events/catalog.py``, E16-S1-T2) validate against the catalog via
:func:`~backend.events.catalog.make_envelope`, and that the role mapping
(``backend/api/timeline_roles.py``, E16-S1-T3) resolves each mapped E2 agent
role onto one of those registered event types.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.timeline_roles import (
    TIMELINE_STAGE_ANALYSIS,
    TIMELINE_STAGE_PATCH,
    TIMELINE_STAGE_PLANNING,
    TIMELINE_STAGE_VALIDATION,
    timeline_event_type_for_agent_role,
    timeline_stage_for_agent_role,
)
from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.events.catalog import EVENT_CATALOG, RunTimelineStepData, make_envelope
from backend.llm.factory import get_chat_model
from backend.persistence.database import reset_store_cache

_TIMELINE_EVENT_TYPES = (
    "run.timeline.planning",
    "run.timeline.analysis",
    "run.timeline.patch",
    "run.timeline.validation",
)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """A TestClient on an isolated temp SQLite store, forced onto the stub LLM.

    Mirrors ``backend/tests/test_v2_api_contract.py``'s fixture: turn
    creation drives the same agent pipeline as session creation, so the LLM
    provider must be pinned to the deterministic stub and isolated from the
    repository's persisted ``autodev.config.json``.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'v2-chat-timeline.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # ``backend.api.main`` calls ``load_dotenv(override=True)`` at import time,
    # which walks up from that module's own file location looking for a
    # ``.env`` file. A developer's local ``.env`` sitting anywhere above this
    # test tree (e.g. the parent checkout a worktree is nested under) would
    # otherwise clobber the env vars set above the moment the app is
    # imported. Neutralize it so this fixture's isolation is self-contained.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    reset_runtime_config_cache()
    reset_settings_cache()
    reset_store_cache()
    get_chat_model.cache_clear()
    from backend.api.main import app

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_store_cache()
    reset_runtime_config_cache()
    get_chat_model.cache_clear()


def _create_session(client: TestClient, goal: str = "Ship the v2 turn contract") -> dict:
    """Helper: POST /v2/sessions and return the parsed response body."""
    response = client.post("/v2/sessions", json={"goal": goal})
    assert response.status_code == 201, response.text
    return response.json()


def _create_turn(client: TestClient, session_id: str, message: str = "Please proceed") -> dict:
    """Helper: POST /v2/sessions/{id}/turns and return the parsed response body.

    E43-S6: this now returns immediately with ``status: "running"`` -- the
    agent graph runs in a background job. Use :func:`_poll_turn_until_terminal`
    to wait for the real, completed result.
    """
    response = client.post(f"/v2/sessions/{session_id}/turns", json={"message": message})
    assert response.status_code == 201, response.text
    return response.json()


def _poll_turn_until_terminal(client: TestClient, turn_id: str, *, timeout_s: float = 5.0) -> dict:
    """Poll ``GET /v2/turns/{turn_id}`` until its background run finishes (E43-S6).

    Args:
        client: Test client to poll with.
        turn_id: Turn (run) id to poll.
        timeout_s: Max time to wait before giving up.

    Returns:
        The turn body once ``status`` is no longer ``"running"``.
    """
    deadline = time.monotonic() + timeout_s
    body: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/v2/turns/{turn_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    return body


class TestCreateTurnV2:
    """``POST /v2/sessions/{sessionId}/turns``."""

    def test_create_turn_happy_path(self, client: TestClient) -> None:
        """E43-S6: the turn is created and returned immediately, before the
        agent graph has run -- status "running", empty results/steps -- so
        the caller has a turnId to open a live event stream against right
        away instead of only after the (potentially long) run finishes."""
        session = _create_session(client)
        turn = _create_turn(client, session["session_id"], message="Add a health check endpoint")
        assert turn["schemaVersion"] == "2.0"
        assert turn["sessionId"] == session["session_id"]
        assert turn["message"] == "Add a health check endpoint"
        assert turn["turnId"]
        assert turn["status"] == "running"
        assert turn["runType"]
        assert turn["history"] == []
        assert turn["results"] == []
        assert turn["steps"] == []

    def test_create_turn_eventually_completes_with_real_results(self, client: TestClient) -> None:
        """E43-S6: polling the turn until its background run finishes still
        shows the stub agent pipeline's real, non-empty results/steps --
        catches a conversion bug that would silently drop them just as the
        old synchronous-response assertion did."""
        session = _create_session(client)
        turn = _create_turn(client, session["session_id"], message="Add a health check endpoint")
        completed = _poll_turn_until_terminal(client, turn["turnId"])
        assert completed["status"] == "completed"
        assert isinstance(completed["history"], list)
        assert len(completed["results"]) > 0
        assert len(completed["steps"]) > 0

    def test_create_turn_unknown_session_returns_standard_error_envelope(self, client: TestClient) -> None:
        response = client.post("/v2/sessions/no-such-session/turns", json={"message": "hello"})
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["schemaVersion"] == "2.0"
        assert detail["error"]["code"] == 404

    def test_create_turn_validation_error_shape(self, client: TestClient) -> None:
        session = _create_session(client)
        response = client.post(f"/v2/sessions/{session['session_id']}/turns", json={"message": ""})
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert isinstance(detail, list)
        assert any(item.get("loc", [])[-1] == "message" for item in detail)

    def test_create_turn_at_the_tenant_concurrency_ceiling_returns_429(self, client: TestClient) -> None:
        """A tenant already at its concurrent-run quota gets 429, not a new run (ADR-019)."""
        from backend.persistence.tenancy import DEFAULT_TENANT_ID
        from backend.quotas.contracts import RunBudgetLimits, TenantQuotaPolicy
        from backend.quotas.service import QuotaService

        quota_service = QuotaService()
        quota_service.set_policy(
            TenantQuotaPolicy(
                tenant_id=DEFAULT_TENANT_ID,
                max_concurrent_runs=1,
                max_storage_bytes=10_000_000,
                monthly_token_limit=1_000_000,
                monthly_cost_microusd=1_000_000,
                requests_per_second=10,
                default_run_budget=RunBudgetLimits(),
            )
        )
        lease = quota_service.acquire_run_lease(tenant_id=DEFAULT_TENANT_ID, run_id="already-running")
        assert lease.granted

        session = _create_session(client)
        response = client.post(f"/v2/sessions/{session['session_id']}/turns", json={"message": "hi"})
        assert response.status_code == 429

        quota_service.release_run_lease("already-running")


class TestGetTurnV2:
    """``GET /v2/turns/{turnId}``."""

    def test_get_turn_happy_path(self, client: TestClient) -> None:
        session = _create_session(client)
        created = _create_turn(client, session["session_id"], message="Investigate the failing test")
        body = _poll_turn_until_terminal(client, created["turnId"])
        assert body["schemaVersion"] == "2.0"
        assert body["turnId"] == created["turnId"]
        assert body["sessionId"] == session["session_id"]
        assert body["message"] == "Investigate the failing test"
        assert body["status"] == "completed"
        assert len(body["results"]) > 0
        assert len(body["steps"]) > 0

    def test_get_turn_unknown_returns_standard_error_envelope(self, client: TestClient) -> None:
        response = client.get("/v2/turns/no-such-turn")
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["schemaVersion"] == "2.0"
        assert detail["error"]["code"] == 404


class TestListSessionTurnsV2:
    """``GET /v2/sessions/{sessionId}/turns``."""

    def test_list_turns_happy_path_empty(self, client: TestClient) -> None:
        session = _create_session(client)
        response = client.get(f"/v2/sessions/{session['session_id']}/turns")
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["items"] == []
        assert body["page"] == {"limit": 20, "offset": 0, "total": 0}

    def test_list_turns_paginated(self, client: TestClient) -> None:
        session = _create_session(client)
        _create_turn(client, session["session_id"], message="First turn")
        _create_turn(client, session["session_id"], message="Second turn")
        response = client.get(f"/v2/sessions/{session['session_id']}/turns", params={"limit": 1, "offset": 0})
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert len(body["items"]) == 1
        assert body["page"] == {"limit": 1, "offset": 0, "total": 2}

    def test_list_turns_second_page(self, client: TestClient) -> None:
        session = _create_session(client)
        _create_turn(client, session["session_id"], message="First turn")
        _create_turn(client, session["session_id"], message="Second turn")
        response = client.get(f"/v2/sessions/{session['session_id']}/turns", params={"limit": 1, "offset": 1})
        assert response.status_code == 200
        assert len(response.json()["items"]) == 1

    def test_list_turns_unknown_session_returns_standard_error_envelope(self, client: TestClient) -> None:
        response = client.get("/v2/sessions/no-such-session/turns")
        assert response.status_code == 404
        assert response.json()["detail"]["schemaVersion"] == "2.0"


class TestTimelineEventTaxonomyV2:
    """``run.timeline.*`` catalog additions (E16-S1-T2)."""

    def test_timeline_event_types_registered_with_shared_payload_model(self) -> None:
        for event_type in _TIMELINE_EVENT_TYPES:
            assert event_type in EVENT_CATALOG
            definition = EVENT_CATALOG[event_type]
            assert definition.data_model is RunTimelineStepData
            assert definition.partition == "runId"

    @pytest.mark.parametrize("event_type", _TIMELINE_EVENT_TYPES)
    def test_make_envelope_validates_timeline_event(self, event_type: str) -> None:
        envelope = make_envelope(
            event_type,
            tenant_id="acme",
            partition_key="run_1",
            data={
                "stepKey": "step-1",
                "actorRole": "coder",
                "status": "completed",
                "output": "$ pytest -q\n1 passed in 0.01s",
            },
            subject={"runId": "run_1"},
        )
        assert envelope.type == event_type
        assert envelope.partitionKey == "run_1"
        assert envelope.data["actorRole"] == "coder"
        assert envelope.data["output"] == "$ pytest -q\n1 passed in 0.01s"

    def test_make_envelope_rejects_timeline_event_missing_actor_role(self) -> None:
        with pytest.raises(Exception):
            make_envelope(
                "run.timeline.planning",
                tenant_id="acme",
                partition_key="run_1",
                data={"stepKey": "step-1", "status": "completed", "output": "log"},
            )


class TestTimelineRoleMappingV2:
    """E2 agent role -> timeline stage/event mapping (E16-S1-T3)."""

    @pytest.mark.parametrize(
        ("agent_role", "expected_stage", "expected_event_type"),
        [
            ("planner", TIMELINE_STAGE_PLANNING, "run.timeline.planning"),
            ("navigator", TIMELINE_STAGE_ANALYSIS, "run.timeline.analysis"),
            ("analyzer", TIMELINE_STAGE_ANALYSIS, "run.timeline.analysis"),
            ("coder", TIMELINE_STAGE_PATCH, "run.timeline.patch"),
            ("validator", TIMELINE_STAGE_VALIDATION, "run.timeline.validation"),
        ],
    )
    def test_mapped_roles_resolve_to_registered_event_types(
        self, agent_role: str, expected_stage: str, expected_event_type: str
    ) -> None:
        assert timeline_stage_for_agent_role(agent_role) == expected_stage
        event_type = timeline_event_type_for_agent_role(agent_role)
        assert event_type == expected_event_type
        assert event_type in EVENT_CATALOG

    @pytest.mark.parametrize("agent_role", ["architect", "devops", "responder", "unknown-role"])
    def test_unmapped_roles_return_none(self, agent_role: str) -> None:
        assert timeline_stage_for_agent_role(agent_role) is None
        assert timeline_event_type_for_agent_role(agent_role) is None
