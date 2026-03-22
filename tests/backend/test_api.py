"""API integration tests for durable orchestration endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, get_orchestrator
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import DurableStore, reset_store_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    database_path = tmp_path / "api-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    reset_store_cache()
    get_orchestrator.cache_clear()
    app.dependency_overrides[get_orchestrator] = lambda: OrchestratorService(
        store=DurableStore(f"sqlite:///{database_path}")
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_orchestrator.cache_clear()
    reset_store_cache()


def test_agent_contract_endpoint(client: TestClient) -> None:
    response = client.get("/agents/contracts")

    assert response.status_code == 200
    payload = response.json()
    assert "planner" in payload["contracts"]
    assert payload["contracts"]["planner"]["properties"]["steps"]["type"] == "array"
    assert "validator" in payload["contracts"]


def test_session_and_run_endpoints(client: TestClient) -> None:
    plan_response = client.post("/plan", json={"goal": "Ship durable control plane"})
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    assert plan_payload["status"] == "awaiting_input"

    session_id = plan_payload["session_id"]

    chat_response = client.post(
        "/chat",
        json={"session_id": session_id, "message": "Execute the first iteration"},
    )
    assert chat_response.status_code == 200
    chat_payload = chat_response.json()
    assert chat_payload["status"] == "completed"
    assert chat_payload["run_id"]
    assert chat_payload["run_type"] == "existing_repo_change"
    assert chat_payload["current_state"] == "completed"
    assert chat_payload["steps"][0]["step_key"] == "navigator"

    session_response = client.get(f"/sessions/{session_id}")
    assert session_response.status_code == 200
    assert len(session_response.json()["history"]) >= len(chat_payload["history"])

    sessions_response = client.get("/sessions")
    assert sessions_response.status_code == 200
    assert sessions_response.json()[0]["session_id"] == session_id

    runs_response = client.get(f"/sessions/{session_id}/runs")
    assert runs_response.status_code == 200
    runs_payload = runs_response.json()
    assert len(runs_payload) == 1
    assert runs_payload[0]["trigger_message"] == "Execute the first iteration"
    assert runs_payload[0]["run_type"] == "existing_repo_change"
    assert runs_payload[0]["steps"]
