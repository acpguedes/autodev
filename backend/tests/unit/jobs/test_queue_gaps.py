"""Unit tests filling coverage gaps in ``backend/jobs/queue.py``.

Complements ``backend/tests/test_job_queue.py`` (not modified here) by
exercising: ``RedisJobQueue.get()`` for an unknown job id, ``_run_redis_job``
error paths (handler exception, missing handler), ``run_pending_once()`` on
an empty queue, ``RedisJobQueue.__init__`` failure paths (missing package,
missing URL), ``get_queue()`` with an explicit ``Settings`` object for both
backends, and ``_decode_value`` with ``bytes`` input.

A fake, in-memory Redis client is used throughout — no live Redis service or
network access is required.
"""

from __future__ import annotations

import sys
from typing import Any, Generator

import pytest

from backend.config.settings import Settings
from backend.jobs.queue import (
    RedisJobQueue,
    _decode_value,
    _reset_queue_singleton,
    get_queue,
    register_handler,
)


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


@pytest.fixture(autouse=True)
def _clean_singleton() -> Generator[None, None, None]:
    """Ensure the module-level queue singleton never leaks between tests."""
    _reset_queue_singleton()
    yield
    _reset_queue_singleton()


# ---------------------------------------------------------------------------
# RedisJobQueue.get() — unknown job id
# ---------------------------------------------------------------------------


def test_redis_queue_get_unknown_job_id_returns_error_record() -> None:
    """Fetching an unregistered job id from the Redis-backed queue returns an error record."""
    queue = RedisJobQueue(client=_FakeRedisQueueClient(), start_worker=False)

    record = queue.get("never-enqueued")

    assert record["status"] == "error"
    assert record["result"] is None
    assert "Unknown job_id" in record["error"]


# ---------------------------------------------------------------------------
# _run_redis_job — error paths
# ---------------------------------------------------------------------------


def test_redis_queue_job_with_missing_handler_reaches_error_status() -> None:
    """A job whose ``job_type`` has no registered handler reaches error status."""
    client = _FakeRedisQueueClient()
    queue = RedisJobQueue(client=client, start_worker=False)

    job_id = queue.enqueue("no_such_handler_registered", {})
    ran = queue.run_pending_once()
    record = queue.get(job_id)

    assert ran is True
    assert record["status"] == "error"
    assert "No handler registered" in record["error"]


def test_redis_queue_job_handler_exception_reaches_error_status() -> None:
    """A handler that raises leaves the job in error status with the exception message."""

    @register_handler("unit_test_raising_handler")
    def _boom(_payload: dict) -> Any:
        """Deliberately raise to exercise the error path of ``_run_redis_job``."""
        raise ValueError("handler blew up")

    client = _FakeRedisQueueClient()
    queue = RedisJobQueue(client=client, start_worker=False)

    job_id = queue.enqueue("unit_test_raising_handler", {})
    queue.run_pending_once()
    record = queue.get(job_id)

    assert record["status"] == "error"
    assert record["result"] is None
    assert "handler blew up" in record["error"]


def test_run_redis_job_on_missing_record_is_a_noop() -> None:
    """Running a job id that was never persisted to Redis does nothing and does not raise."""
    client = _FakeRedisQueueClient()
    queue = RedisJobQueue(client=client, start_worker=False)

    queue._run_redis_job("ghost-job-id")  # noqa: SLF001 - exercising the internal guard directly

    assert client.hashes == {}


# ---------------------------------------------------------------------------
# run_pending_once() — empty queue
# ---------------------------------------------------------------------------


def test_run_pending_once_returns_false_when_queue_is_empty() -> None:
    """``run_pending_once`` returns ``False`` without side effects when nothing is queued."""
    queue = RedisJobQueue(client=_FakeRedisQueueClient(), start_worker=False)

    assert queue.run_pending_once() is False


# ---------------------------------------------------------------------------
# RedisJobQueue.__init__ — failure paths
# ---------------------------------------------------------------------------


def test_redis_queue_init_raises_when_redis_package_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing a ``RedisJobQueue`` without the ``redis`` package raises ``RuntimeError``."""
    monkeypatch.setitem(sys.modules, "redis", None)

    with pytest.raises(RuntimeError, match="redis package is not installed"):
        RedisJobQueue(url="redis://localhost:6379/0")


def test_redis_queue_init_raises_when_url_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing a ``RedisJobQueue`` with no URL configured raises ``RuntimeError``."""
    monkeypatch.delenv("AUTODEV_REDIS_URL", raising=False)

    with pytest.raises(RuntimeError, match="AUTODEV_REDIS_URL is required"):
        RedisJobQueue(url=None)


# ---------------------------------------------------------------------------
# get_queue() — explicit Settings, both backends
# ---------------------------------------------------------------------------


def test_get_queue_with_explicit_inprocess_settings() -> None:
    """Passing ``Settings(autodev_job_backend="inprocess")`` selects the in-process queue."""
    from backend.jobs.queue import InProcessJobQueue  # noqa: PLC0415

    settings = Settings(autodev_job_backend="inprocess")

    queue = get_queue(settings)

    assert isinstance(queue, InProcessJobQueue)


def test_get_queue_with_explicit_redis_settings_builds_redis_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing ``Settings(autodev_job_backend="redis")`` selects the Redis-backed queue.

    The real :class:`RedisJobQueue` is monkeypatched out so this exercises only
    the factory's branch selection, never a live Redis connection.
    """
    captured: dict[str, Any] = {}

    class _FakeRedisJobQueue:
        """Stand-in for :class:`RedisJobQueue` capturing the URL it was built with."""

        def __init__(self, *, url: str | None = None, **_kwargs: Any) -> None:
            """Record the connection URL passed by the factory."""
            captured["url"] = url

    monkeypatch.setattr("backend.jobs.queue.RedisJobQueue", _FakeRedisJobQueue)
    settings = Settings(autodev_job_backend="redis", autodev_redis_url="redis://example:6379/1")

    queue = get_queue(settings)

    assert isinstance(queue, _FakeRedisJobQueue)
    assert captured["url"] == "redis://example:6379/1"


# ---------------------------------------------------------------------------
# _decode_value
# ---------------------------------------------------------------------------


def test_decode_value_decodes_bytes() -> None:
    """``_decode_value`` decodes ``bytes`` payloads returned by real Redis clients."""
    assert _decode_value(b"hello") == "hello"


def test_decode_value_stringifies_non_bytes() -> None:
    """``_decode_value`` stringifies non-``bytes``, non-``str`` values."""
    assert _decode_value(42) == "42"
