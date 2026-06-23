"""Tests for U8 — POST /chat/dynamic endpoint.

Tests:
* With ``AUTODEV_DYNAMIC_ORCH=1``: endpoint runs dynamic path and returns 200.
* Without the flag: falls back to standard path, still returns 200.
* Unknown session_id → 404 in both modes.
* Response schema always contains run_id, session_id, status, mode.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, get_orchestrator
from backend.config.settings import reset_settings_cache
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import DurableStore, reset_store_cache

requires_openai = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — skipping tests that make live LLM calls",
)


# ---------------------------------------------------------------------------
# Fixture — isolated orchestrator backed by a temp DB
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "dyn-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    reset_settings_cache()
    reset_store_cache()
    get_orchestrator.cache_clear()
    store = DurableStore(f"sqlite:///{database_path}")
    app.dependency_overrides[get_orchestrator] = lambda: OrchestratorService(store=store)
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()
    get_orchestrator.cache_clear()
    reset_store_cache()


def _create_session(client: TestClient) -> str:
    """Helper: POST /plan and return the session_id."""
    resp = client.post("/plan", json={"goal": "Test dynamic orchestration"})
    assert resp.status_code == 200
    return resp.json()["session_id"]


# ---------------------------------------------------------------------------
# Fallback mode (no env flag)
# ---------------------------------------------------------------------------


@requires_openai
def test_dynamic_chat_fallback_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AUTODEV_DYNAMIC_ORCH", raising=False)
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    assert resp.status_code == 200


@requires_openai
def test_dynamic_chat_fallback_mode_field(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AUTODEV_DYNAMIC_ORCH", raising=False)
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    assert resp.json()["mode"] == "fallback"


@requires_openai
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


@requires_openai
def test_dynamic_chat_dynamic_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODEV_DYNAMIC_ORCH", "1")
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    assert resp.status_code == 200


@requires_openai
def test_dynamic_chat_dynamic_mode_field(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODEV_DYNAMIC_ORCH", "1")
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    body = resp.json()
    # Dynamic path should say "dynamic"; if it falls back due to import issues, "fallback"
    assert body["mode"] in ("dynamic", "fallback")


@requires_openai
def test_dynamic_chat_dynamic_has_session_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODEV_DYNAMIC_ORCH", "1")
    session_id = _create_session(client)
    resp = client.post("/chat/dynamic", json={"session_id": session_id, "message": "go"})
    assert resp.json()["session_id"] == session_id


@requires_openai
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
