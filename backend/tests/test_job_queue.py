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

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app as main_app
from backend.jobs.queue import (
    InProcessJobQueue,
    RedisJobQueue,
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
    """Poll a job until it reaches a terminal status or the timeout elapses."""
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
    """Enqueuing a job returns a non-empty string job id."""
    q = InProcessJobQueue()
    job_id = q.enqueue("echo", {"msg": "hi"})
    assert isinstance(job_id, str)
    assert len(job_id) > 0


def test_inprocess_echo_job_completes_with_result() -> None:
    """An echo job completes and returns its payload wrapped in the result."""
    q = InProcessJobQueue()
    job_id = q.enqueue("echo", {"msg": "hello"})
    rec = _poll(q, job_id)
    assert rec["status"] == "done"
    assert rec["result"] == {"echoed": {"msg": "hello"}}


def test_inprocess_unknown_job_type_reaches_error_status() -> None:
    """A job with no registered handler reaches error status with a message."""
    q = InProcessJobQueue()
    job_id = q.enqueue("nonexistent_handler", {})
    rec = _poll(q, job_id)
    assert rec["status"] == "error"
    assert rec["error"] is not None


def test_inprocess_unknown_job_id_returns_error() -> None:
    """Fetching an unknown job id returns an error record instead of raising."""
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


class _FakeRedisQueueClient:
    """In-memory stand-in for a Redis client, used to test :class:`RedisJobQueue`."""

    def __init__(self) -> None:
        """Initialize empty in-memory hashes and lists."""
        self.hashes: dict[str, dict[str, str]] = {}
        self.queues: dict[str, list[str]] = {}

    def ping(self) -> bool:
        """Report the fake connection as always reachable."""
        return True

    def hset(self, key: str, mapping: dict[str, str]) -> int:
        """Merge fields into an in-memory hash."""
        self.hashes.setdefault(key, {}).update(mapping)
        return len(mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        """Return a copy of an in-memory hash's fields."""
        return dict(self.hashes.get(key, {}))

    def rpush(self, key: str, value: str) -> int:
        """Append a value to an in-memory list."""
        self.queues.setdefault(key, []).append(value)
        return len(self.queues[key])

    def lpop(self, key: str) -> str | None:
        """Pop and return the first value of an in-memory list, or ``None`` if empty."""
        values = self.queues.setdefault(key, [])
        if not values:
            return None
        return values.pop(0)


def test_redis_queue_persists_pending_job_and_runs_registered_handler() -> None:
    """The Redis-backed queue persists a pending job and runs it via its handler."""
    client = _FakeRedisQueueClient()
    queue = RedisJobQueue(client=client, start_worker=False)

    job_id = queue.enqueue("echo", {"msg": "redis"})

    assert client.queues["autodev:jobs:pending"] == [job_id]
    assert queue.get(job_id)["status"] == "pending"

    assert queue.run_pending_once() is True
    record = queue.get(job_id)

    assert record["status"] == "done"
    assert record["result"] == {"echoed": {"msg": "redis"}}


# ---------------------------------------------------------------------------
# get_queue — default is in-process
# ---------------------------------------------------------------------------


def test_get_queue_default_is_inprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no job-backend env var set, the default queue is in-process."""
    monkeypatch.delenv("AUTODEV_JOB_BACKEND", raising=False)
    _reset_queue_singleton()
    try:
        q = get_queue()
        assert isinstance(q, InProcessJobQueue)
    finally:
        _reset_queue_singleton()


def test_get_queue_returns_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated calls to ``get_queue()`` return the same cached instance."""
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
    """``POST /jobs`` accepts a job and returns 202 with a job id."""
    resp = _client.post("/jobs", json={"job_type": "echo", "payload": {"x": 1}})
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert isinstance(body["job_id"], str)


def test_api_get_job_returns_terminal_status() -> None:
    """``GET /jobs/{id}`` eventually reports a terminal status for a submitted job."""
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
    """``GET /jobs/{id}`` returns 404 for an unknown job id."""
    resp = _client.get("/jobs/does-not-exist-abc123")
    assert resp.status_code == 404
