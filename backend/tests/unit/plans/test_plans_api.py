"""Tests for U10 — Plans API: GET/PUT/approve/reject.

Each test gets an isolated SQLite DB via monkeypatching DATABASE_URL.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.persistence.database import reset_store_cache


SESSION_ID = "test-session-plans-001"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    db_path = tmp_path / "plans-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_store_cache()
    with TestClient(app) as tc:
        yield tc
    reset_store_cache()


# ---------------------------------------------------------------------------
# GET — 404 when missing
# ---------------------------------------------------------------------------


def test_get_plan_404_when_absent(client: TestClient) -> None:
    resp = client.get(f"/plans/{SESSION_ID}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT — upsert
# ---------------------------------------------------------------------------


def test_put_plan_returns_200(client: TestClient) -> None:
    resp = client.put(f"/plans/{SESSION_ID}", json={"steps": ["step-a", "step-b"]})
    assert resp.status_code == 200


def test_put_plan_body_contains_steps(client: TestClient) -> None:
    client.put(f"/plans/{SESSION_ID}", json={"steps": ["step-a", "step-b"]})
    body = client.put(f"/plans/{SESSION_ID}", json={"steps": ["step-a", "step-b"]}).json()
    assert body["steps"] == ["step-a", "step-b"]


def test_put_plan_resets_status_to_draft(client: TestClient) -> None:
    resp = client.put(f"/plans/{SESSION_ID}", json={"steps": ["x"]})
    assert resp.json()["status"] == "draft"


# ---------------------------------------------------------------------------
# PUT → GET round-trip
# ---------------------------------------------------------------------------


def test_get_plan_after_put_returns_200(client: TestClient) -> None:
    client.put(f"/plans/{SESSION_ID}", json={"steps": ["step-1", "step-2", "step-3"]})
    resp = client.get(f"/plans/{SESSION_ID}")
    assert resp.status_code == 200


def test_get_plan_round_trips_steps(client: TestClient) -> None:
    steps = ["step-1", "step-2", "step-3"]
    client.put(f"/plans/{SESSION_ID}", json={"steps": steps})
    body = client.get(f"/plans/{SESSION_ID}").json()
    assert body["steps"] == steps
    assert body["session_id"] == SESSION_ID


def test_put_overwrites_existing_steps(client: TestClient) -> None:
    client.put(f"/plans/{SESSION_ID}", json={"steps": ["old"]})
    client.put(f"/plans/{SESSION_ID}", json={"steps": ["new-a", "new-b"]})
    body = client.get(f"/plans/{SESSION_ID}").json()
    assert body["steps"] == ["new-a", "new-b"]


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


def test_approve_returns_200(client: TestClient) -> None:
    client.put(f"/plans/{SESSION_ID}", json={"steps": ["s"]})
    resp = client.post(
        f"/plans/{SESSION_ID}/approve",
        json={"actor": "alice", "note": "looks good"},
    )
    assert resp.status_code == 200


def test_approve_sets_status_approved(client: TestClient) -> None:
    client.put(f"/plans/{SESSION_ID}", json={"steps": ["s"]})
    client.post(f"/plans/{SESSION_ID}/approve", json={"actor": "alice"})
    body = client.get(f"/plans/{SESSION_ID}").json()
    assert body["status"] == "approved"


def test_approve_unknown_session_returns_404(client: TestClient) -> None:
    resp = client.post("/plans/no-such-session/approve", json={"actor": "alice"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------


def test_reject_returns_200(client: TestClient) -> None:
    client.put(f"/plans/{SESSION_ID}", json={"steps": ["s"]})
    resp = client.post(
        f"/plans/{SESSION_ID}/reject",
        json={"actor": "bob", "note": "needs revision"},
    )
    assert resp.status_code == 200


def test_reject_sets_status_rejected(client: TestClient) -> None:
    client.put(f"/plans/{SESSION_ID}", json={"steps": ["s"]})
    client.post(f"/plans/{SESSION_ID}/reject", json={"actor": "bob", "note": "nope"})
    body = client.get(f"/plans/{SESSION_ID}").json()
    assert body["status"] == "rejected"


def test_reject_unknown_session_returns_404(client: TestClient) -> None:
    resp = client.post("/plans/no-such-session/reject", json={"actor": "bob"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Approve then upsert resets to draft
# ---------------------------------------------------------------------------


def test_upsert_after_approve_resets_to_draft(client: TestClient) -> None:
    client.put(f"/plans/{SESSION_ID}", json={"steps": ["s"]})
    client.post(f"/plans/{SESSION_ID}/approve", json={"actor": "alice"})
    client.put(f"/plans/{SESSION_ID}", json={"steps": ["s-revised"]})
    body = client.get(f"/plans/{SESSION_ID}").json()
    assert body["status"] == "draft"
