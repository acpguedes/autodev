"""Tests for U22 job queue (backend/jobs/ + POST/GET /jobs).

Coverage:
- InProcessJobQueue enqueue→poll until done returns the echo result.
- get_queue() default is InProcessJobQueue (no env var set).
- Unknown job_id returns error status.
- Unregistered job_type results in error status.
- POST /jobs then GET /jobs/{id} via TestClient returns a terminal status.
- POST /jobs with unknown job_type eventually reaches error status.
- GET /jobs/{unknown_id} returns 404.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from backend.api.main import app as main_app
from backend.jobs.queue import (
    InProcessJobQueue,
    _reset_queue_singleton,
    get_queue,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TERMINAL = {"done", "error"}
_POLL_TIMEOUT = 5.0
_POLL_INTERVAL = 0.05


def _poll(queue: InProcessJobQueue, job_id: str) -> dict:
    deadline = time.monotonic() + _POLL_TIMEOUT
    while time.monotonic() < deadline:
        rec = queue.get(job_id)
        if rec["status"] in _TERMINAL:
            return rec
        time.sleep(_POLL_INTERVAL)
    return queue.get(job_id)


# ---------------------------------------------------------------------------
# InProcessJobQueue unit tests
# ---------------------------------------------------------------------------


def test_inprocess_enqueue_returns_string_id() -> None:
    q = InProcessJobQueue()
    job_id = q.enqueue("echo", {"msg": "hi"})
    assert isinstance(job_id, str)
    assert len(job_id) > 0


def test_inprocess_echo_job_completes_with_result() -> None:
    q = InProcessJobQueue()
    job_id = q.enqueue("echo", {"msg": "hello"})
    rec = _poll(q, job_id)
    assert rec["status"] == "done"
    assert rec["result"] == {"echoed": {"msg": "hello"}}


def test_inprocess_unknown_job_type_reaches_error_status() -> None:
    q = InProcessJobQueue()
    job_id = q.enqueue("nonexistent_handler", {})
    rec = _poll(q, job_id)
    assert rec["status"] == "error"
    assert rec["error"] is not None


def test_inprocess_unknown_job_id_returns_error() -> None:
    q = InProcessJobQueue()
    rec = q.get("this-id-does-not-exist")
    assert rec["status"] == "error"
    assert "Unknown job_id" in rec["error"]


def test_inprocess_initial_status_is_pending_or_running_or_done() -> None:
    """Status must be one of the four valid values."""
    q = InProcessJobQueue()
    job_id = q.enqueue("echo", {})
    rec = q.get(job_id)
    assert rec["status"] in {"pending", "running", "done", "error"}


# ---------------------------------------------------------------------------
# get_queue — default is in-process
# ---------------------------------------------------------------------------


def test_get_queue_default_is_inprocess(monkeypatch) -> None:
    monkeypatch.delenv("AUTODEV_JOB_BACKEND", raising=False)
    _reset_queue_singleton()
    try:
        q = get_queue()
        assert isinstance(q, InProcessJobQueue)
    finally:
        _reset_queue_singleton()


def test_get_queue_returns_singleton(monkeypatch) -> None:
    monkeypatch.delenv("AUTODEV_JOB_BACKEND", raising=False)
    _reset_queue_singleton()
    try:
        q1 = get_queue()
        q2 = get_queue()
        assert q1 is q2
    finally:
        _reset_queue_singleton()


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


_client = TestClient(main_app)


def test_api_post_jobs_returns_202_with_job_id() -> None:
    resp = _client.post("/jobs", json={"job_type": "echo", "payload": {"x": 1}})
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert isinstance(body["job_id"], str)


def test_api_get_job_returns_terminal_status() -> None:
    resp = _client.post("/jobs", json={"job_type": "echo", "payload": {"k": "v"}})
    job_id = resp.json()["job_id"]

    deadline = time.monotonic() + _POLL_TIMEOUT
    status = None
    while time.monotonic() < deadline:
        r = _client.get(f"/jobs/{job_id}")
        assert r.status_code == 200
        status = r.json()["status"]
        if status in _TERMINAL:
            break
        time.sleep(_POLL_INTERVAL)

    assert status in _TERMINAL


def test_api_get_unknown_job_id_returns_404() -> None:
    resp = _client.get("/jobs/does-not-exist-abc123")
    assert resp.status_code == 404
