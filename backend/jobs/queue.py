"""Async in-process and Redis job-queue implementations."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from opentelemetry.trace import SpanKind

from backend.config.settings import Settings
from backend.observability.context import (
    attach_execution_context,
    capture_execution_context,
)
from backend.observability.metrics import QueueSnapshot
from backend.observability.tracing import get_tracer

class AbstractJobQueue(ABC):
    """Minimal async-job-queue interface."""

    @abstractmethod
    def enqueue(self, job_type: str, payload: dict) -> str:
        """Submit a job and return its unique *job_id*."""

    @abstractmethod
    def get(self, job_id: str) -> dict:
        """Return the five-field public state record for *job_id*."""

    @abstractmethod
    def stats(self) -> QueueSnapshot:
        """Return a bounded snapshot of queue and worker state."""


_JobHandler = Callable[[dict], Any]
_HANDLERS: dict[str, _JobHandler] = {}


def register_handler(job_type: str) -> Callable[[_JobHandler], _JobHandler]:
    """Decorator: register a callable as the handler for *job_type*."""

    def _decorator(fn: _JobHandler) -> _JobHandler:
        """Register the wrapped callable as the handler for the enclosing ``job_type``."""
        _HANDLERS[job_type] = fn
        return fn

    return _decorator


@register_handler("echo")
def _echo(payload: dict) -> dict:
    """Trivial handler that returns its payload unchanged."""
    return {"echoed": payload}


_STATUS_PENDING = "pending"
_STATUS_RUNNING = "running"
_STATUS_DONE = "done"
_STATUS_ERROR = "error"


class InProcessJobQueue(AbstractJobQueue):
    """Thread-pool-backed in-process job queue."""

    def __init__(self, max_workers: int = 4) -> None:
        """Initialize the queue with a bounded thread pool.

        Args:
            max_workers: Maximum number of jobs to run concurrently.
        """
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._max_workers = max_workers
        self._store: dict[str, dict] = {}
        self._execution_contexts: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def enqueue(self, job_type: str, payload: dict) -> str:
        """Submit a job to the thread pool for asynchronous execution.

        Args:
            job_type: Registered job type identifying the handler to run.
            payload: Arguments passed to the handler.

        Returns:
            The generated job id.
        """
        with get_tracer().start_as_current_span(
            "autodev.job.enqueue",
            kind=SpanKind.PRODUCER,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            carrier = capture_execution_context()
            for name, value in _correlation_span_attributes(carrier).items():
                span.set_attribute(name, value)
            job_id = str(uuid.uuid4())
            record: dict = {
                "job_id": job_id, "job_type": job_type,
                "status": _STATUS_PENDING,
                "result": None, "error": None,
            }
            with self._lock:
                self._store[job_id] = record
                self._execution_contexts[job_id] = carrier
            try:
                self._executor.submit(self._run, job_id, job_type, payload)
            except Exception:
                with self._lock:
                    self._store.pop(job_id, None)
                    self._execution_contexts.pop(job_id, None)
                raise
        return job_id

    def get(self, job_id: str) -> dict:
        """Return the current state of a submitted job.

        Args:
            job_id: Identifier returned by :meth:`enqueue`.

        Returns:
            The job's status record; an error record if ``job_id`` is unknown.
        """
        with self._lock:
            record = self._store.get(job_id)
        if record is None:
            return {
                "job_id": job_id, "job_type": "unknown",
                "status": _STATUS_ERROR,
                "result": None, "error": f"Unknown job_id: {job_id!r}",
            }
        return dict(record)

    def stats(self) -> QueueSnapshot:
        """Return pending/running counts and in-process worker utilization.

        Returns:
            A snapshot captured atomically under the queue state lock.
        """
        with self._lock:
            pending = sum(
                record["status"] == _STATUS_PENDING for record in self._store.values()
            )
            running = sum(
                record["status"] == _STATUS_RUNNING for record in self._store.values()
            )
        return QueueSnapshot(pending, running, self._max_workers, running)

    def _run(self, job_id: str, job_type: str, payload: dict) -> None:
        """Execute a job's handler in the worker thread and record its outcome.

        Args:
            job_id: Identifier of the job being run.
            job_type: Registered job type identifying the handler to run.
            payload: Arguments passed to the handler.
        """
        with self._lock:
            self._store[job_id]["status"] = _STATUS_RUNNING
            carrier = self._execution_contexts[job_id]
        try:
            with attach_execution_context(carrier):
                with get_tracer().start_as_current_span(
                    "autodev.job.execute",
                    kind=SpanKind.CONSUMER,
                    attributes=_correlation_span_attributes(carrier),
                    record_exception=False,
                    set_status_on_exception=False,
                ):
                    handler = _HANDLERS.get(job_type)
                    if handler is None:
                        with self._lock:
                            self._store[job_id]["status"] = _STATUS_ERROR
                            self._store[job_id]["error"] = (
                                "No handler registered for job_type "
                                f"{job_type!r}."
                            )
                        return
                    result = handler(payload)
            with self._lock:
                self._store[job_id]["status"] = _STATUS_DONE
                self._store[job_id]["result"] = result
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._store[job_id]["status"] = _STATUS_ERROR
                self._store[job_id]["error"] = str(exc)
        finally:
            with self._lock:
                self._execution_contexts.pop(job_id, None)


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
        """Initialize the queue, connecting to Redis and optionally starting a worker.

        Args:
            client: Pre-built Redis client to reuse; a new one is built if omitted.
            url: Redis connection URL, used when ``client`` is omitted; falls
                back to ``AUTODEV_REDIS_URL``.
            start_worker: Whether to start a background thread processing jobs.
            poll_interval: Seconds to sleep between empty queue polls.

        Raises:
            RuntimeError: If the ``redis`` package is not installed, or if no
                Redis URL is configured.
        """
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
        self._worker_enabled = start_worker
        self._busy_workers = 0
        self._busy_lock = threading.Lock()
        if start_worker:
            thread = threading.Thread(target=self._worker_loop, daemon=True)
            thread.start()

    def enqueue(self, job_type: str, payload: dict) -> str:
        """Submit a job by writing its record to Redis and queuing its id.

        Args:
            job_type: Registered job type identifying the handler to run.
            payload: Arguments passed to the handler.

        Returns:
            The generated job id.
        """
        with get_tracer().start_as_current_span(
            "autodev.job.enqueue",
            kind=SpanKind.PRODUCER,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            carrier = capture_execution_context()
            for name, value in _correlation_span_attributes(carrier).items():
                span.set_attribute(name, value)
            job_id = str(uuid.uuid4())
            key = self._job_key(job_id)
            mapping: Mapping[Any, Any] = {
                "job_id": job_id, "job_type": job_type,
                "payload": json.dumps(payload),
                "status": _STATUS_PENDING,
                "result": "null", "error": "",
                "otel_traceparent": carrier.get("traceparent", ""),
                "otel_tracestate": carrier.get("tracestate", ""),
                "otel_baggage": carrier.get("baggage", ""),
                "correlation_request_id": carrier.get("correlation_request_id", ""),
                "correlation_run_id": carrier.get("correlation_run_id", ""),
                "correlation_tenant_id": carrier.get("correlation_tenant_id", ""),
            }
            self._client.hset(key, mapping=mapping)
            try:
                self._client.rpush(self._pending_key, job_id)
            except Exception:
                try:
                    self._client.delete(key)
                except Exception:
                    self._client.hdel(key, *mapping)
                raise
        return job_id

    def get(self, job_id: str) -> dict:
        """Return the current state of a submitted job from Redis.

        Args:
            job_id: Identifier returned by :meth:`enqueue`.

        Returns:
            The job's status record; an error record if ``job_id`` is unknown.
        """
        record = _decode_hash(self._client.hgetall(self._job_key(job_id)))
        if not record:
            return {
                "job_id": job_id, "job_type": "unknown",
                "status": _STATUS_ERROR,
                "result": None, "error": f"Unknown job_id: {job_id!r}",
            }
        return {
            "job_id": record["job_id"], "job_type": record["job_type"],
            "status": record["status"],
            "result": json.loads(record.get("result") or "null"),
            "error": record.get("error") or None,
        }

    def stats(self) -> QueueSnapshot:
        """Return Redis queue depth and worker activity owned by this process.

        Returns:
            Pending list depth plus current-process worker state.
        """
        pending = int(self._client.llen(self._pending_key))
        with self._busy_lock:
            busy_workers = self._busy_workers
        return QueueSnapshot(
            pending, busy_workers, 1 if self._worker_enabled else 0, busy_workers
        )

    def run_pending_once(self) -> bool:
        """Pop and run a single pending job, if any.

        Returns:
            ``True`` if a job was popped and run, ``False`` if the queue was empty.
        """
        raw_job_id = self._client.lpop(self._pending_key)
        if raw_job_id is None:
            return False
        job_id = _decode_value(raw_job_id)
        self._run_redis_job(job_id)
        return True

    def _worker_loop(self) -> None:
        """Continuously run pending jobs, sleeping between empty polls."""
        while True:
            ran_job = self.run_pending_once()
            if not ran_job:
                time.sleep(self._poll_interval)

    def _run_redis_job(self, job_id: str) -> None:
        """Execute a job's handler and persist its outcome back to Redis.

        Args:
            job_id: Identifier of the job to run.
        """
        key = self._job_key(job_id)
        record = _decode_hash(self._client.hgetall(key))
        if not record:
            return
        carrier = {
            "traceparent": record.get("otel_traceparent", ""),
            "tracestate": record.get("otel_tracestate", ""),
            "baggage": record.get("otel_baggage", ""),
            "correlation_request_id": record.get("correlation_request_id", ""),
            "correlation_run_id": record.get("correlation_run_id", ""),
            "correlation_tenant_id": record.get("correlation_tenant_id", ""),
        }
        with self._busy_lock:
            self._busy_workers += 1
        try:
            self._client.hset(key, mapping={"status": _STATUS_RUNNING})
            with attach_execution_context(carrier):
                with get_tracer().start_as_current_span(
                    "autodev.job.execute",
                    kind=SpanKind.CONSUMER,
                    attributes=_correlation_span_attributes(carrier),
                    record_exception=False,
                    set_status_on_exception=False,
                ):
                    handler = _HANDLERS.get(record["job_type"])
                    if handler is None:
                        self._client.hset(
                            key,
                            mapping={
                                "status": _STATUS_ERROR,
                                "error": "No handler registered for job_type "
                                f"{record['job_type']!r}.",
                            },
                        )
                        return
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
                    "status": _STATUS_ERROR, "result": "null", "error": str(exc),
                },
            )
        finally:
            self._client.hdel(key, *_REDIS_EXECUTION_CONTEXT_FIELDS)
            with self._busy_lock:
                self._busy_workers -= 1

    def _job_key(self, job_id: str) -> str:
        """Build the Redis hash key storing ``job_id``."""
        return f"autodev:jobs:{job_id}"


def _decode_value(value: Any) -> str:
    """Decode a Redis response value to a ``str``.

    Args:
        value: Raw value returned by the Redis client, bytes or otherwise.

    Returns:
        The decoded string.
    """
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _decode_hash(record: dict[Any, Any]) -> dict[str, str]:
    """Decode a Redis hash response into a plain ``str``-keyed/valued dict.

    Args:
        record: Raw hash mapping returned by the Redis client.

    Returns:
        The decoded mapping.
    """
    return {_decode_value(key): _decode_value(value) for key, value in record.items()}


_REDIS_EXECUTION_CONTEXT_FIELDS = (
    "otel_traceparent",
    "otel_tracestate",
    "otel_baggage",
    "correlation_request_id",
    "correlation_run_id",
    "correlation_tenant_id",
)


def _correlation_span_attributes(carrier: Mapping[str, str]) -> dict[str, str]:
    """Build content-free span attributes from a sanitized execution carrier."""
    keys = {
        "correlation_request_id": "autodev.request_id",
        "correlation_run_id": "autodev.run_id",
        "correlation_step_id": "autodev.step_id",
        "correlation_tenant_id": "autodev.tenant_id",
    }
    return {
        attribute: carrier[key]
        for key, attribute in keys.items()
        if carrier.get(key)
    }


_queue_singleton: AbstractJobQueue | None = None
_queue_lock = threading.Lock()


def get_queue(settings: Settings | None = None) -> AbstractJobQueue:
    """Return the configured process-wide queue singleton."""
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
