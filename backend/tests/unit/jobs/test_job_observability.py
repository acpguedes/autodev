"""Job-queue tracing, context propagation, and USE-metric tests."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry.trace import SpanKind

from backend.api import main as api_main
from backend.config.settings import Settings
from backend.jobs.queue import (
    _HANDLERS,
    AbstractJobQueue,
    InProcessJobQueue,
    RedisJobQueue,
)
from backend.observability.context import bind_correlation_context
from backend.observability.metrics import QueueSnapshot, get_metric_sink
from backend.observability.tracing import get_tracer
from backend.tests.observability_helpers import capture_observability

_TEST_HANDLER_NAMES = {"observability-blocking", "observability-raising", "observability-returning", "redis-observability-blocking"}


class _FakeRedisQueueClient:
    """Thread-safe in-memory Redis subset used by queue observability tests."""

    def __init__(self) -> None:
        """Initialize empty hashes and lists guarded by one lock."""
        self.hashes: dict[str, dict[str, str]] = {}
        self.queues: dict[str, list[str]] = {}
        self.expiries: dict[str, int] = {}
        self._lock = threading.Lock()

    def ping(self) -> bool:
        """Report the fake connection as reachable."""
        return True

    def hset(self, key: str, mapping: dict[str, str]) -> int:
        """Merge fields into an in-memory hash."""
        with self._lock:
            self.hashes.setdefault(key, {}).update(mapping)
        return len(mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        """Return a copy of an in-memory hash."""
        with self._lock:
            return dict(self.hashes.get(key, {}))

    def hdel(self, key: str, *fields: str) -> int:
        """Delete fields from an in-memory hash."""
        deleted = 0
        with self._lock:
            record = self.hashes.setdefault(key, {})
            for field in fields:
                if field in record:
                    deleted += 1
                    del record[field]
        return deleted

    def rpush(self, key: str, value: str) -> int:
        """Append a value to an in-memory list."""
        with self._lock:
            values = self.queues.setdefault(key, [])
            values.append(value)
            return len(values)

    def lpop(self, key: str) -> str | None:
        """Pop the first list value, or return ``None`` when empty."""
        with self._lock:
            values = self.queues.setdefault(key, [])
            return values.pop(0) if values else None

    def llen(self, key: str) -> int:
        """Return the current length of an in-memory list."""
        with self._lock:
            return len(self.queues.setdefault(key, []))

    def blpop(self, keys: list[str], timeout: float = 0) -> tuple[str, str] | None:
        """Pop and return ``(key, value)`` from the first non-empty list, or ``None``."""
        with self._lock:
            for key in keys:
                values = self.queues.setdefault(key, [])
                if values:
                    return key, values.pop(0)
        return None

    def expire(self, key: str, seconds: int) -> bool:
        """Record the TTL a caller requested for *key*."""
        with self._lock:
            self.expiries[key] = seconds
            return key in self.hashes


def _wait_for_stats(
    queue: AbstractJobQueue,
    predicate: Callable[[QueueSnapshot], bool],
    *,
    timeout_seconds: float = 1.0,
) -> QueueSnapshot:
    """Wait for queue statistics to satisfy a bounded predicate.

    Args:
        queue: Queue whose current snapshot should be inspected.
        predicate: Condition identifying the expected snapshot.
        timeout_seconds: Maximum number of seconds to wait.

    Returns:
        The first matching snapshot.

    Raises:
        AssertionError: If no snapshot matches before the deadline.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        snapshot = queue.stats()
        if predicate(snapshot):
            return snapshot
        time.sleep(0.01)
    raise AssertionError("queue stats did not reach the expected state")


def _wait_for_job(
    queue: AbstractJobQueue,
    job_id: str,
    *,
    timeout_seconds: float = 1.0,
) -> dict:
    """Wait for a queued job to reach a terminal state.

    Args:
        queue: Queue holding the job.
        job_id: Identifier returned by ``enqueue``.
        timeout_seconds: Maximum number of seconds to wait.

    Returns:
        The terminal public job record.

    Raises:
        AssertionError: If the job does not finish before the deadline.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        record = queue.get(job_id)
        if record["status"] in {"done", "error"}:
            return record
        time.sleep(0.01)
    raise AssertionError("job did not reach a terminal state")


def _shutdown_inprocess_queue(queue: InProcessJobQueue) -> None:
    """Close a directly constructed queue's executor after a test."""
    queue._executor.shutdown(wait=True)  # noqa: SLF001 - queue owns no public shutdown API


def _metric_value(metrics_data: Any, name: str, **attributes: str) -> float:
    """Read one exact observable-gauge point from exported metric data.

    Args:
        metrics_data: OpenTelemetry SDK metrics data returned by the reader.
        name: Instrument name to locate.
        **attributes: Exact point attributes to match.

    Returns:
        The matching numeric value.

    Raises:
        AssertionError: If the requested point is absent.
    """
    for resource_metric in metrics_data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name != name:
                    continue
                for point in metric.data.data_points:
                    if dict(point.attributes) == attributes:
                        return float(point.value)
    raise AssertionError(f"metric point not found: {name} {attributes}")


def test_abstract_queue_requires_stats_implementation() -> None:
    """A queue backend without ``stats`` cannot satisfy the abstract contract."""

    class _QueueWithoutStats(AbstractJobQueue):
        """Deliberately incomplete queue implementation."""

        def enqueue(self, job_type: str, payload: dict) -> str:
            """Return a fixed id without scheduling work."""
            return "job-id"

        def get(self, job_id: str) -> dict:
            """Return a minimal completed record."""
            return {
                "job_id": job_id,
                "job_type": "test",
                "status": "done",
                "result": None,
                "error": None,
            }

    with pytest.raises(TypeError, match="stats"):
        _QueueWithoutStats()  # type: ignore[abstract]


def test_inprocess_queue_reports_pending_running_and_worker_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In-process snapshots distinguish queued work from one busy worker."""
    release = threading.Event()
    monkeypatch.setitem(
        _HANDLERS, "observability-blocking", lambda payload: release.wait(timeout=1)
    )
    queue = InProcessJobQueue(max_workers=1)
    second_job: str | None = None
    try:
        first_job = queue.enqueue("observability-blocking", {})
        _wait_for_stats(queue, lambda value: value.running == 1)
        second_job = queue.enqueue("observability-blocking", {})

        snapshot = _wait_for_stats(
            queue, lambda value: value.pending == 1 and value.running == 1
        )

        assert snapshot == QueueSnapshot(
            pending=1,
            running=1,
            workers=1,
            busy_workers=1,
        )
    finally:
        release.set()
        _wait_for_job(queue, first_job)
        if second_job is not None:
            _wait_for_job(queue, second_job)
        _shutdown_inprocess_queue(queue)


def test_job_consumer_continues_producer_trace_and_domain_context() -> None:
    """A consumer span is parented to enqueue and restores bounded domain ids."""
    queue = InProcessJobQueue(max_workers=1)
    try:
        with capture_observability() as capture:
            with bind_correlation_context(run_id="run-1", tenant_id="tenant-1"):
                with get_tracer().start_as_current_span("request"):
                    job_id = queue.enqueue("echo", {"message": "domain-data"})
            record = _wait_for_job(queue, job_id)
            assert record["status"] == "done"
            capture.runtime.force_flush()
            spans = capture.span_exporter.get_finished_spans()

        producer = next(span for span in spans if span.name == "autodev.job.enqueue")
        consumer = next(span for span in spans if span.name == "autodev.job.execute")
        assert producer.kind is SpanKind.PRODUCER
        assert consumer.kind is SpanKind.CONSUMER
        assert consumer.parent is not None
        assert consumer.parent.span_id == producer.context.span_id
        consumer_attributes = consumer.attributes
        assert consumer_attributes is not None
        assert consumer_attributes["autodev.run_id"] == "run-1"
        assert consumer_attributes["autodev.tenant_id"] == "tenant-1"
    finally:
        _shutdown_inprocess_queue(queue)


def test_job_context_is_internal_and_cleaned_after_completion() -> None:
    """Execution carriers never alter public records and are removed at terminal state."""
    queue = InProcessJobQueue(max_workers=1)
    try:
        job_id = queue.enqueue("echo", {"secret": "payload-remains-domain-data"})
        record = _wait_for_job(queue, job_id)

        assert set(record) == {"job_id", "job_type", "status", "result", "error"}
        assert job_id not in queue._execution_contexts  # noqa: SLF001
    finally:
        _shutdown_inprocess_queue(queue)


def test_job_spans_never_record_payload_result_or_raw_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queue spans omit payloads, results, and raw handler exceptions."""

    def _return_private_content(_payload: dict) -> dict[str, str]:
        """Return domain content that must stay outside telemetry."""
        return {"private": "raw-private-result"}

    def _raise_with_private_content(_payload: dict) -> None:
        """Raise an error containing text that must stay outside telemetry."""
        raise RuntimeError("raw-private-error")

    monkeypatch.setitem(_HANDLERS, "observability-returning", _return_private_content)
    monkeypatch.setitem(_HANDLERS, "observability-raising", _raise_with_private_content)
    queue = InProcessJobQueue(max_workers=1)
    try:
        with capture_observability() as capture:
            result_job_id = queue.enqueue(
                "observability-returning", {"secret": "raw-private-payload"}
            )
            error_job_id = queue.enqueue(
                "observability-raising", {"secret": "raw-private-payload"}
            )
            result_record = _wait_for_job(queue, result_job_id)
            error_record = _wait_for_job(queue, error_job_id)
            assert result_record["result"] == {"private": "raw-private-result"}
            assert error_record["error"] == "raw-private-error"
            capture.runtime.force_flush()
            spans = capture.span_exporter.get_finished_spans()

        telemetry = repr(
            [
                (span.attributes, span.events, span.status.description)
                for span in spans
                if span.name.startswith("autodev.job.")
            ]
        )
        assert {span.name for span in spans if span.name.startswith("autodev.job.")} == {
            "autodev.job.enqueue",
            "autodev.job.execute",
        }
        assert "raw-private-payload" not in telemetry
        assert "raw-private-result" not in telemetry
        assert "raw-private-error" not in telemetry
    finally:
        _shutdown_inprocess_queue(queue)


def test_redis_queue_persists_private_carrier_outside_public_record() -> None:
    """Redis stores the fixed internal carrier fields and removes them after use."""
    client = _FakeRedisQueueClient()
    queue = RedisJobQueue(client=client, start_worker=False)
    carrier_fields = {
        "otel_traceparent",
        "otel_tracestate",
        "otel_baggage",
        "correlation_request_id",
        "correlation_run_id",
        "correlation_tenant_id",
    }

    with capture_observability():
        with bind_correlation_context(
            request_id="request-1", run_id="run-1", tenant_id="tenant-1"
        ):
            with get_tracer().start_as_current_span("redis-request"):
                job_id = queue.enqueue("echo", {"message": "redis-domain-data"})

        private_record = client.hgetall(f"autodev:jobs:{job_id}")
        public_record = queue.get(job_id)
        assert carrier_fields <= set(private_record)
        assert private_record["correlation_request_id"] == "request-1"
        assert private_record["correlation_run_id"] == "run-1"
        assert private_record["correlation_tenant_id"] == "tenant-1"
        assert json.loads(private_record["payload"]) == {
            "message": "redis-domain-data"
        }
        assert set(public_record) == {
            "job_id",
            "job_type",
            "status",
            "result",
            "error",
        }

        assert queue.run_pending_once() is True

    assert not carrier_fields & set(client.hgetall(f"autodev:jobs:{job_id}"))


def test_redis_queue_reports_llen_and_current_process_busy_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis snapshots use LLEN and count only work active in this process."""
    release = threading.Event()
    monkeypatch.setitem(
        _HANDLERS,
        "redis-observability-blocking",
        lambda payload: release.wait(timeout=1),
    )
    client = _FakeRedisQueueClient()
    queue = RedisJobQueue(client=client, start_worker=False)
    job_id = queue.enqueue("redis-observability-blocking", {})

    assert queue.stats() == QueueSnapshot(
        pending=1,
        running=0,
        workers=0,
        busy_workers=0,
    )

    runner = threading.Thread(target=queue.run_pending_once)
    runner.start()
    try:
        snapshot = _wait_for_stats(queue, lambda value: value.busy_workers == 1)
        assert snapshot == QueueSnapshot(
            pending=0,
            running=1,
            workers=0,
            busy_workers=1,
        )
    finally:
        release.set()
        runner.join(timeout=1)
    assert not runner.is_alive()
    assert queue.get(job_id)["status"] == "done"


def test_redis_queue_reports_one_worker_only_when_background_worker_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis worker capacity reflects whether its background thread is enabled."""
    started: list[bool] = []

    class _DormantThread:
        """Thread stand-in that records startup without running the infinite loop."""

        def __init__(self, *, target: Callable[[], None], daemon: bool) -> None:
            """Capture the requested worker target and daemon flag."""
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            """Record that the queue enabled its background worker."""
            started.append(True)

    monkeypatch.setattr("backend.jobs.queue.threading.Thread", _DormantThread)
    disabled = RedisJobQueue(client=_FakeRedisQueueClient(), start_worker=False)
    enabled = RedisJobQueue(client=_FakeRedisQueueClient(), start_worker=True)

    assert disabled.stats().workers == 0
    assert enabled.stats().workers == 1
    assert started == [True]


def test_queue_and_worker_observable_gauges_use_snapshot_callback() -> None:
    """Queue and worker gauges export the current backend snapshot."""
    queue = InProcessJobQueue(max_workers=4)
    try:
        with capture_observability() as capture:
            get_metric_sink().observe_queue(
                backend="inprocess",
                callback=queue.stats,
            )
            capture.runtime.force_flush()
            metrics_data = capture.metric_reader.get_metrics_data()

        assert metrics_data is not None
        assert _metric_value(
            metrics_data,
            "autodev.queue.jobs",
            backend="inprocess",
            state="pending",
        ) == 0
        assert _metric_value(
            metrics_data,
            "autodev.worker.utilization",
            backend="inprocess",
        ) == 0.0
    finally:
        _shutdown_inprocess_queue(queue)


def test_lifespan_registers_selected_queue_snapshot_with_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application startup registers the selected queue on the configured runtime."""
    queue = InProcessJobQueue(max_workers=3)
    observed: dict[str, Any] = {}

    class _MetricSink:
        """Capture the queue observation registered during startup."""

        def observe_queue(
            self, *, backend: str, callback: Callable[[], QueueSnapshot]
        ) -> None:
            """Store the backend and callback supplied by lifespan."""
            observed["backend"] = backend
            observed["callback"] = callback

    runtime = SimpleNamespace(metric_sink=_MetricSink())
    monkeypatch.setattr(api_main, "get_settings", Settings)
    monkeypatch.setattr(api_main, "configure_observability", lambda settings: runtime)
    monkeypatch.setattr(api_main, "get_queue", lambda settings: queue)
    monkeypatch.setattr(
        api_main,
        "get_runtime_config_service",
        lambda: SimpleNamespace(apply_to_environment=lambda: None),
    )
    monkeypatch.setattr(api_main, "get_orchestrator", lambda: None)
    monkeypatch.setattr(api_main, "shutdown_observability", lambda: None)

    async def _exercise_lifespan() -> None:
        """Enter and exit application startup around one assertion point."""
        async with api_main.lifespan(api_main.app):
            assert observed["backend"] == "inprocess"
            assert observed["callback"]() == QueueSnapshot(
                pending=0,
                running=0,
                workers=3,
                busy_workers=0,
            )

    try:
        asyncio.run(_exercise_lifespan())
    finally:
        _shutdown_inprocess_queue(queue)


def test_observability_tests_do_not_leak_global_handlers() -> None:
    """Test-owned handlers are absent from the process-global registry."""
    assert _TEST_HANDLER_NAMES.isdisjoint(_HANDLERS)
