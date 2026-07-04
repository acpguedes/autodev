"""Async job-queue abstraction with an in-process default.

``InProcessJobQueue`` runs jobs in a ``ThreadPoolExecutor`` and keeps results
in a plain dict — suitable for development and single-process deployments.

``RedisJobQueue`` persists job state in Redis and runs registered handlers from
the current worker process.

``get_queue()`` returns the module-level ``InProcessJobQueue`` singleton by
default.
"""

from __future__ import annotations

import os
import json
import threading
import time
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from backend.config.settings import Settings

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
# Redis queue
# ---------------------------------------------------------------------------


class RedisJobQueue(AbstractJobQueue):
    """Redis-backed queue for production-like deployments."""

    _pending_key = "autodev:jobs:pending"

    def __init__(
        self,
        *,
        client: Any | None = None,
        url: str | None = None,
        start_worker: bool = True,
        poll_interval: float = 0.1,
    ) -> None:
        if client is None:
            try:
                import redis as _redis  # type: ignore[import-untyped]
            except ImportError as exc:
                raise RuntimeError("redis package is not installed.") from exc

            redis_url = (url or os.environ.get("AUTODEV_REDIS_URL", "")).strip()
            if not redis_url:
                raise RuntimeError("AUTODEV_REDIS_URL is required for RedisJobQueue.")
            client = _redis.from_url(redis_url)

        self._client = client
        self._client.ping()
        self._poll_interval = poll_interval
        if start_worker:
            thread = threading.Thread(target=self._worker_loop, daemon=True)
            thread.start()

    def enqueue(self, job_type: str, payload: dict) -> str:
        job_id = str(uuid.uuid4())
        self._client.hset(
            self._job_key(job_id),
            mapping={
                "job_id": job_id,
                "job_type": job_type,
                "payload": json.dumps(payload),
                "status": _STATUS_PENDING,
                "result": "null",
                "error": "",
            },
        )
        self._client.rpush(self._pending_key, job_id)
        return job_id

    def get(self, job_id: str) -> dict:
        record = _decode_hash(self._client.hgetall(self._job_key(job_id)))
        if not record:
            return {
                "job_id": job_id,
                "job_type": "unknown",
                "status": _STATUS_ERROR,
                "result": None,
                "error": f"Unknown job_id: {job_id!r}",
            }
        return {
            "job_id": record["job_id"],
            "job_type": record["job_type"],
            "status": record["status"],
            "result": json.loads(record.get("result") or "null"),
            "error": record.get("error") or None,
        }

    def run_pending_once(self) -> bool:
        raw_job_id = self._client.lpop(self._pending_key)
        if raw_job_id is None:
            return False
        job_id = _decode_value(raw_job_id)
        self._run_redis_job(job_id)
        return True

    def _worker_loop(self) -> None:
        while True:
            ran_job = self.run_pending_once()
            if not ran_job:
                time.sleep(self._poll_interval)

    def _run_redis_job(self, job_id: str) -> None:
        key = self._job_key(job_id)
        record = _decode_hash(self._client.hgetall(key))
        if not record:
            return

        self._client.hset(key, mapping={"status": _STATUS_RUNNING})
        handler = _HANDLERS.get(record["job_type"])
        if handler is None:
            self._client.hset(
                key,
                mapping={
                    "status": _STATUS_ERROR,
                    "error": f"No handler registered for job_type {record['job_type']!r}.",
                },
            )
            return

        try:
            result = handler(json.loads(record.get("payload") or "{}"))
            self._client.hset(
                key,
                mapping={
                    "status": _STATUS_DONE,
                    "result": json.dumps(result),
                    "error": "",
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._client.hset(
                key,
                mapping={
                    "status": _STATUS_ERROR,
                    "result": "null",
                    "error": str(exc),
                },
            )

    def _job_key(self, job_id: str) -> str:
        return f"autodev:jobs:{job_id}"


def _decode_value(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _decode_hash(record: dict[Any, Any]) -> dict[str, str]:
    return {_decode_value(key): _decode_value(value) for key, value in record.items()}


# ---------------------------------------------------------------------------
# Factory / singleton
# ---------------------------------------------------------------------------

_queue_singleton: AbstractJobQueue | None = None
_queue_lock = threading.Lock()


def get_queue(settings: Settings | None = None) -> AbstractJobQueue:
    """Return the active job queue (singleton).

    Returns :class:`RedisJobQueue` only when ``redis`` is importable **and**
    ``AUTODEV_JOB_BACKEND`` equals ``"redis"`` (case-insensitive).
    Otherwise returns :class:`InProcessJobQueue`.
    """
    global _queue_singleton

    with _queue_lock:
        if _queue_singleton is not None:
            return _queue_singleton

        if settings is None:
            want_redis = os.environ.get("AUTODEV_JOB_BACKEND", "").strip().lower() == "redis"
            redis_url = os.environ.get("AUTODEV_REDIS_URL", "")
        else:
            want_redis = settings.autodev_job_backend == "redis"
            redis_url = settings.autodev_redis_url
        if want_redis:
            _queue_singleton = RedisJobQueue(url=redis_url)
            return _queue_singleton

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
