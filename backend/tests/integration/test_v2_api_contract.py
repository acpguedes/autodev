"""E9-S1 API contract tests for the ``/v2`` Control Plane API (T4).

Exercises each new ``/v2`` resource (sessions, runs, execution plans,
config) for: a happy path, the standardized validation-error shape,
pagination, and ``schemaVersion`` presence on every response.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.llm.factory import get_chat_model
from backend.persistence.database import reset_store_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """A TestClient on an isolated temp SQLite store, forced onto the stub LLM.

    Mirrors ``backend/tests/test_dynamic_chat_api.py``'s isolation: the
    ``/v2/sessions`` create endpoint drives the planner agent, so the LLM
    provider must be pinned to the deterministic stub and isolated from the
    repository's persisted ``autodev.config.json``.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'v2-api.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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


def _create_session(client: TestClient, goal: str = "Ship the v2 control plane API") -> dict:
    """Helper: POST /v2/sessions and return the parsed response body."""
    response = client.post("/v2/sessions", json={"goal": goal})
    assert response.status_code == 201, response.text
    return response.json()


class TestSessionsV2:
    """``/v2/sessions`` create, list, get."""

    def test_create_session_happy_path(self, client: TestClient) -> None:
        body = _create_session(client)
        assert body["schemaVersion"] == "2.0"
        assert body["goal"] == "Ship the v2 control plane API"
        assert body["session_id"]
        assert body["history"] == []

    def test_create_session_validation_error_shape(self, client: TestClient) -> None:
        response = client.post("/v2/sessions", json={"goal": ""})
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert isinstance(detail, list)
        assert any(item.get("loc", [])[-1] == "goal" for item in detail)

    def test_list_sessions_paginated(self, client: TestClient) -> None:
        _create_session(client, goal="First goal")
        _create_session(client, goal="Second goal")
        response = client.get("/v2/sessions", params={"limit": 1, "offset": 0})
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert len(body["items"]) == 1
        assert body["page"] == {"limit": 1, "offset": 0, "total": 2}

    def test_list_sessions_second_page(self, client: TestClient) -> None:
        _create_session(client, goal="First goal")
        _create_session(client, goal="Second goal")
        response = client.get("/v2/sessions", params={"limit": 1, "offset": 1})
        assert response.status_code == 200
        assert len(response.json()["items"]) == 1

    def test_get_session_happy_path(self, client: TestClient) -> None:
        created = _create_session(client)
        response = client.get(f"/v2/sessions/{created['session_id']}")
        assert response.status_code == 200
        assert response.json()["session_id"] == created["session_id"]

    def test_get_session_unknown_returns_standard_error_envelope(self, client: TestClient) -> None:
        response = client.get("/v2/sessions/no-such-session")
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["schemaVersion"] == "2.0"
        assert detail["error"]["code"] == 404


class TestSessionRunsV2:
    """``/v2/sessions/{id}/runs``."""

    def test_list_runs_happy_path_empty(self, client: TestClient) -> None:
        created = _create_session(client)
        response = client.get(f"/v2/sessions/{created['session_id']}/runs")
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["items"] == []
        assert body["page"] == {"limit": 20, "offset": 0, "total": 0}

    def test_list_runs_unknown_session_returns_standard_error_envelope(self, client: TestClient) -> None:
        response = client.get("/v2/sessions/no-such-session/runs")
        assert response.status_code == 404
        assert response.json()["detail"]["schemaVersion"] == "2.0"


class TestExecutionPlanV2:
    """``/v2/sessions/{id}/execution-plan`` and its ``/execute`` action."""

    def test_get_execution_plan_before_analysis(self, client: TestClient) -> None:
        created = _create_session(client)
        response = client.get(f"/v2/sessions/{created['session_id']}/execution-plan")
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["tasks"] == []
        assert body["status"] == "awaiting_input"

    def test_get_execution_plan_unknown_session(self, client: TestClient) -> None:
        response = client.get("/v2/sessions/no-such-session/execution-plan")
        assert response.status_code == 404
        assert response.json()["detail"]["schemaVersion"] == "2.0"

    def test_execute_plan_with_no_tasks_returns_400(self, client: TestClient) -> None:
        created = _create_session(client)
        response = client.post(f"/v2/sessions/{created['session_id']}/execution-plan/execute")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["schemaVersion"] == "2.0"
        assert detail["error"]["code"] == 400

    def test_execute_plan_unknown_session(self, client: TestClient) -> None:
        response = client.post("/v2/sessions/no-such-session/execution-plan/execute")
        assert response.status_code == 404
        assert response.json()["detail"]["schemaVersion"] == "2.0"


class TestConfigV2:
    """``/v2/config`` get/update."""

    def test_get_config_happy_path(self, client: TestClient) -> None:
        response = client.get("/v2/config")
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert "config" in body
        assert "instructions" in body

    def test_update_config_round_trip(self, client: TestClient) -> None:
        current = client.get("/v2/config").json()
        updated_config = dict(current["config"])
        updated_config["repository"] = {
            **updated_config["repository"],
            "repository_label": "Updated via /v2/config test",
        }
        response = client.put("/v2/config", json={"config": updated_config})
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["config"]["repository"]["repository_label"] == "Updated via /v2/config test"

    def test_update_config_validation_error_shape(self, client: TestClient) -> None:
        response = client.put("/v2/config", json={"config": {"llm": {"temperature": "not-a-number"}}})
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)
