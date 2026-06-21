"""Async job-queue abstraction with an in-process default.

``InProcessJobQueue`` runs jobs in a ``ThreadPoolExecutor`` and keeps results
in a plain dict — suitable for development and single-process deployments.

``RedisJobQueue`` is a stub selected only when **both**:
- ``redis`` is importable (optional dependency), **and**
- the env var ``AUTODEV_JOB_BACKEND`` equals ``"redis"`` (case-insensitive).

``get_queue()`` returns the module-level ``InProcessJobQueue`` singleton by
default.
"""

from __future__ import annotations

import os
import threading
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class AbstractJobQueue(ABC):
    """Minimal async-job-queue interface."""

    @abstractmethod
    def enqueue(self, job_type: str, payload: dict) -> str:
        """Submit a job and return its unique *job_id*."""

    @abstractmethod
    def get(self, job_id: str) -> dict:
        """Return the current state of *job_id*.

        The returned dict always contains:
        - ``job_id``: str
        - ``job_type``: str
        - ``status``: one of ``"pending"`` | ``"running"`` | ``"done"`` | ``"error"``
        - ``result``: any (``None`` while pending/running)
        - ``error``: str | None
        """


# ---------------------------------------------------------------------------
# Built-in job handlers
# ---------------------------------------------------------------------------

_JobHandler = Callable[[dict], Any]

_HANDLERS: dict[str, _JobHandler] = {}


def register_handler(job_type: str) -> Callable[[_JobHandler], _JobHandler]:
    """Decorator: register a callable as the handler for *job_type*."""

    def _decorator(fn: _JobHandler) -> _JobHandler:
        _HANDLERS[job_type] = fn
        return fn

    return _decorator


@register_handler("echo")
def _echo(payload: dict) -> dict:
    """Trivial handler that returns its payload unchanged."""
    return {"echoed": payload}


# ---------------------------------------------------------------------------
# In-process queue
# ---------------------------------------------------------------------------

_STATUS_PENDING = "pending"
_STATUS_RUNNING = "running"
_STATUS_DONE = "done"
_STATUS_ERROR = "error"


class InProcessJobQueue(AbstractJobQueue):
    """Thread-pool-backed in-process job queue."""

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._store: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, job_type: str, payload: dict) -> str:
        job_id = str(uuid.uuid4())
        record: dict = {
            "job_id": job_id,
            "job_type": job_type,
            "status": _STATUS_PENDING,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._store[job_id] = record

        self._executor.submit(self._run, job_id, job_type, payload)
        return job_id

    def get(self, job_id: str) -> dict:
        with self._lock:
            record = self._store.get(job_id)
        if record is None:
            return {
                "job_id": job_id,
                "job_type": "unknown",
                "status": _STATUS_ERROR,
                "result": None,
                "error": f"Unknown job_id: {job_id!r}",
            }
        return dict(record)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self, job_id: str, job_type: str, payload: dict) -> None:
        with self._lock:
            self._store[job_id]["status"] = _STATUS_RUNNING

        handler = _HANDLERS.get(job_type)
        if handler is None:
            with self._lock:
                self._store[job_id]["status"] = _STATUS_ERROR
                self._store[job_id]["error"] = f"No handler registered for job_type {job_type!r}."
            return

        try:
            result = handler(payload)
            with self._lock:
                self._store[job_id]["status"] = _STATUS_DONE
                self._store[job_id]["result"] = result
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._store[job_id]["status"] = _STATUS_ERROR
                self._store[job_id]["error"] = str(exc)


# ---------------------------------------------------------------------------
# Redis stub (optional)
# ---------------------------------------------------------------------------


class RedisJobQueue(AbstractJobQueue):
    """Stub implementation backed by Redis.

    Selected only when ``redis`` is importable AND
    ``AUTODEV_JOB_BACKEND=redis``.  Raises ``RuntimeError`` on any call when
    the real Redis connection is not configured.
    """

    def __init__(self) -> None:
        try:
            import redis as _redis  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("redis package is not installed.") from exc

        url = os.environ.get("AUTODEV_REDIS_URL", "redis://localhost:6379/0")
        self._client = _redis.from_url(url)

    def enqueue(self, job_type: str, payload: dict) -> str:  # pragma: no cover
        raise NotImplementedError("RedisJobQueue.enqueue is a stub.")

    def get(self, job_id: str) -> dict:  # pragma: no cover
        raise NotImplementedError("RedisJobQueue.get is a stub.")


# ---------------------------------------------------------------------------
# Factory / singleton
# ---------------------------------------------------------------------------

_queue_singleton: AbstractJobQueue | None = None
_queue_lock = threading.Lock()


def get_queue() -> AbstractJobQueue:
    """Return the active job queue (singleton).

    Returns :class:`RedisJobQueue` only when ``redis`` is importable **and**
    ``AUTODEV_JOB_BACKEND`` equals ``"redis"`` (case-insensitive).
    Otherwise returns :class:`InProcessJobQueue`.
    """
    global _queue_singleton

    with _queue_lock:
        if _queue_singleton is not None:
            return _queue_singleton

        want_redis = (
            os.environ.get("AUTODEV_JOB_BACKEND", "").strip().lower() == "redis"
        )
        if want_redis:
            try:
                _queue_singleton = RedisJobQueue()
                return _queue_singleton
            except (RuntimeError, ImportError):
                pass

        _queue_singleton = InProcessJobQueue()
        return _queue_singleton


def _reset_queue_singleton() -> None:
    """Test helper — reset the singleton so tests can get a fresh queue."""
    global _queue_singleton
    with _queue_lock:
        _queue_singleton = None


__all__ = [
    "AbstractJobQueue",
    "InProcessJobQueue",
    "RedisJobQueue",
    "get_queue",
    "register_handler",
    "_reset_queue_singleton",
]
