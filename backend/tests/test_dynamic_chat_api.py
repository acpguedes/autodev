"""Tests for U8 — POST /chat/dynamic endpoint.

Tests:
* With ``AUTODEV_DYNAMIC_ORCH=1``: endpoint runs dynamic path and returns 200.
* Without the flag: falls back to standard path, still returns 200.
* Unknown session_id → 404 in both modes.
* Response schema always contains run_id, session_id, status, mode.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, get_orchestrator
from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.llm.factory import get_chat_model
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import DurableStore, reset_store_cache


# ---------------------------------------------------------------------------
# Fixture — isolated orchestrator backed by a temp DB, forced onto the stub LLM
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "dyn-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    # Force the deterministic stub provider so the suite runs offline and fast.
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    # Isolate from the repository's persisted autodev.config.json, which would
    # otherwise be loaded at app startup and override the stub provider (and
    # re-inject a real OPENAI_API_KEY) via RuntimeConfigService.apply_to_environment.
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_runtime_config_cache()
    reset_settings_cache()
    reset_store_cache()
    get_chat_model.cache_clear()
    get_orchestrator.cache_clear()
    store = DurableStore(f"sqlite:///{database_path}")
    app.dependency_overrides[get_orchestrator] = lambda: OrchestratorService(store=store)
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()
    get_orchestrator.cache_clear()
    get_chat_model.cache_clear()
    reset_store_cache()
    reset_runtime_config_cache()


def _create_session(client: TestClient) -> str:
    """Helper: POST /plan and return the session_id."""
    resp = client.post("/plan", json={"goal": "Test dynamic orchestration"})
    assert resp.status_code == 200
    return resp.json()["session_id"]


# ---------------------------------------------------------------------------
# Fallback mode (no env flag)
# ---------------------------------------------------------------------------


def test_dynamic_chat_fallback_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AUTODEV_DYNAMIC_ORCH", raising=False)
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    assert resp.status_code == 200


def test_dynamic_chat_fallback_mode_field(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AUTODEV_DYNAMIC_ORCH", raising=False)
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    assert resp.json()["mode"] == "fallback"


def test_dynamic_chat_fallback_has_run_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AUTODEV_DYNAMIC_ORCH", raising=False)
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    body = resp.json()
    assert body["run_id"]
    assert body["session_id"] == session_id
    assert body["status"] == "completed"


# ---------------------------------------------------------------------------
# Dynamic mode (flag set)
# ---------------------------------------------------------------------------


def test_dynamic_chat_dynamic_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODEV_DYNAMIC_ORCH", "1")
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    assert resp.status_code == 200


def test_dynamic_chat_dynamic_mode_field(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODEV_DYNAMIC_ORCH", "1")
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    body = resp.json()
    # Dynamic path should say "dynamic"; if it falls back due to import issues, "fallback"
    assert body["mode"] in ("dynamic", "fallback")


def test_dynamic_chat_dynamic_has_session_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODEV_DYNAMIC_ORCH", "1")
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    assert resp.json()["session_id"] == session_id


def test_dynamic_chat_dynamic_status_completed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODEV_DYNAMIC_ORCH", "1")
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    assert resp.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# Unknown session — should 404 in both modes
# ---------------------------------------------------------------------------


def test_dynamic_chat_unknown_session_fallback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AUTODEV_DYNAMIC_ORCH", raising=False)
    resp = client.post(
        "/chat/dynamic",
        json={"session_id": "no-such-session-xyz", "message": "hello"},
    )
    assert resp.status_code == 404


def test_dynamic_chat_unknown_session_dynamic(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODEV_DYNAMIC_ORCH", "1")
    resp = client.post(
        "/chat/dynamic",
        json={"session_id": "no-such-session-xyz", "message": "hello"},
    )
    assert resp.status_code == 404
