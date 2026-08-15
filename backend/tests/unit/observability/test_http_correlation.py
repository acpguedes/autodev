"""Tests for safe HTTP trace, metric, log, and request-ID correlation."""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import HistogramDataPoint
from opentelemetry.trace import SpanKind, StatusCode
from starlette.types import Message, Receive, Send

import backend.observability.middleware as middleware_module
from backend.observability.middleware import (
    MetricsRegistry,
    RequestTracingMiddleware,
    attach,
)
from backend.tests.observability_helpers import (
    ObservabilityCapture,
    capture_observability,
)


def _make_app() -> FastAPI:
    """Build an instrumented app with one dynamic route.

    Returns:
        An isolated FastAPI application.
    """
    app = FastAPI()
    attach(app)

    @app.get("/items/{item_id}")
    def get_item(item_id: str, response: Response) -> dict[str, str]:
        """Return one item while exercising response-header replacement."""
        response.headers["x-request-id"] = "application-generated-id"
        return {"item_id": item_id}

    return app


def _make_failing_app(secret: str) -> FastAPI:
    """Build an instrumented app whose route raises secret-bearing text.

    Args:
        secret: Sensitive marker embedded in the raised exception.

    Returns:
        An isolated failing FastAPI application.
    """
    app = FastAPI()
    attach(app)

    @app.get("/boom")
    def boom() -> None:
        """Raise a controlled exception used to test telemetry redaction."""
        raise RuntimeError(f"provider rejected credential {secret}")

    return app


def _metric_points(
    capture: ObservabilityCapture, instrument_name: str
) -> tuple[HistogramDataPoint, ...]:
    """Return collected points for one named metric instrument.

    Args:
        capture: Active in-memory observability capture.
        instrument_name: Exact OpenTelemetry instrument name.

    Returns:
        All points exported for the named instrument.
    """
    metrics_data = capture.metric_reader.get_metrics_data()
    assert metrics_data is not None
    for resource_metric in metrics_data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == instrument_name:
                    return cast(
                        tuple[HistogramDataPoint, ...], tuple(metric.data.data_points)
                    )
    return ()


def test_server_span_uses_incoming_w3c_parent_and_request_id() -> None:
    """The server span continues its remote parent and echoes one safe request ID."""
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    parent_span_id = "b7ad6b7169203331"
    with capture_observability() as capture:
        response = TestClient(_make_app()).get(
            "/items/42",
            headers={
                "traceparent": f"00-{trace_id}-{parent_span_id}-01",
                "x-request-id": "request-upstream-1",
            },
        )

    server = next(
        span
        for span in capture.span_exporter.get_finished_spans()
        if span.kind is SpanKind.SERVER
    )
    assert f"{server.context.trace_id:032x}" == trace_id
    assert server.parent is not None
    assert f"{server.parent.span_id:016x}" == parent_span_id
    assert response.headers.get_list("x-request-id") == ["request-upstream-1"]
    assert server.name == "GET /items/{item_id}"
    assert server.attributes == {
        "http.request.method": "GET",
        "http.route": "/items/{item_id}",
        "http.response.status_code": 200,
        "autodev.request_id": "request-upstream-1",
    }


def test_unsafe_request_id_is_replaced_without_telemetry_leak() -> None:
    """An overlong upstream request ID is replaced and never reaches telemetry."""
    unsafe_request_id = "unsafe-upstream-" + ("x" * 140)
    stream = io.StringIO()
    with capture_observability(log_stream=stream) as capture:
        response = TestClient(_make_app()).get(
            "/items/42", headers={"x-request-id": unsafe_request_id}
        )
        capture.runtime.force_flush()

    request_id = response.headers["x-request-id"]
    assert str(uuid.UUID(request_id)) == request_id
    assert request_id != unsafe_request_id
    assert response.headers.get_list("x-request-id") == [request_id]

    server = next(
        span
        for span in capture.span_exporter.get_finished_spans()
        if span.kind is SpanKind.SERVER
    )
    assert server.attributes is not None
    assert server.attributes["autodev.request_id"] == request_id
    assert unsafe_request_id not in repr(server.attributes)
    assert unsafe_request_id not in repr(server.events)

    rendered = stream.getvalue()
    exported = repr(capture.log_exporter.get_finished_logs())
    assert f'"request_id":"{request_id}"' in rendered
    assert unsafe_request_id not in rendered
    assert unsafe_request_id not in exported


def test_http_metric_and_completion_log_use_route_template_and_trace() -> None:
    """Dynamic requests share a route metric and emit correlated safe completion logs."""
    stream = io.StringIO()
    with capture_observability(log_stream=stream) as capture:
        client = TestClient(_make_app())
        client.get("/items/customer-a")
        client.get("/items/customer-b")
        points = _metric_points(capture, "http.server.request.duration")
        capture.runtime.force_flush()

    assert {(point.attributes or {})["http.route"] for point in points} == {
        "/items/{item_id}"
    }
    assert "customer-a" not in repr(points)
    assert "customer-b" not in repr(points)
    assert any(point.exemplars for point in points)

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    completions = [
        record
        for record in records
        if record.get("event") == "http.request.completed"
    ]
    assert len(completions) == 2
    assert {record["route"] for record in completions} == {"/items/{item_id}"}
    assert all(record.get("trace_id") and record.get("span_id") for record in completions)
    assert all(record.get("request_id") for record in completions)
    assert "customer-a" not in repr(completions)
    assert "customer-b" not in repr(completions)


def test_unmatched_request_uses_bounded_fallback_route() -> None:
    """An unmatched request records only the stable fallback route label."""
    registry = MetricsRegistry()
    import backend.observability.middleware as middleware_module

    original_registry = middleware_module._registry
    middleware_module._registry = registry
    try:
        with capture_observability() as capture:
            response = TestClient(_make_app()).get("/missing/customer-secret")
            points = _metric_points(capture, "http.server.request.duration")
    finally:
        middleware_module._registry = original_registry

    assert response.status_code == 404
    assert {(point.attributes or {})["http.route"] for point in points} == {
        "_unmatched"
    }
    assert set(registry.snapshot()) == {("GET", "_unmatched")}
    assert "customer-secret" not in repr(points)


def test_cancelled_request_is_repropagated_without_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client cancellation stays benign while emitting bounded completion data."""
    cancellation_secret = "cancel-secret-material"
    raw_path = "/stream/customer-private"
    route_template = "/stream/{run_id}"
    registry = MetricsRegistry()
    monkeypatch.setattr(middleware_module, "_registry", registry)

    async def cancelling_app(scope: dict, receive: Receive, send: Send) -> None:
        """Populate the matched route and simulate a cancelled ASGI request."""
        del receive, send
        scope["route"] = SimpleNamespace(path=route_template)
        raise asyncio.CancelledError(cancellation_secret)

    async def receive() -> Message:
        """Return an empty request message if the application receives one."""
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        """Collect any response messages emitted before cancellation."""
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": raw_path, "headers": []}
    stream = io.StringIO()
    middleware = RequestTracingMiddleware(cancelling_app)
    with capture_observability(log_stream=stream) as capture:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(middleware(scope, receive, send))
        points = _metric_points(capture, "http.server.request.duration")
        capture.runtime.force_flush()

    assert sent == []
    server = next(
        span
        for span in capture.span_exporter.get_finished_spans()
        if span.kind is SpanKind.SERVER
    )
    assert server.status.status_code is StatusCode.UNSET
    assert server.attributes is not None
    assert server.attributes["http.route"] == route_template
    assert server.attributes["http.response.status_code"] == 0
    assert cancellation_secret not in repr(server.attributes)
    assert cancellation_secret not in repr(server.events)
    assert raw_path not in repr(server.attributes)

    assert len(points) == 1
    assert points[0].attributes == {
        "http.request.method": "GET",
        "http.route": route_template,
        "http.response.status_code": 0,
    }
    assert points[0].exemplars
    assert cancellation_secret not in repr(points)
    assert raw_path not in repr(points)

    entry = registry.snapshot()[("GET", route_template)]
    assert entry.count == 1
    assert entry.errors == 0

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    completions = [
        record
        for record in records
        if record.get("event") == "http.request.completed"
    ]
    assert len(completions) == 1
    assert completions[0]["route"] == route_template
    assert completions[0]["status"] == 0
    assert completions[0].get("trace_id") and completions[0].get("span_id")
    assert cancellation_secret not in repr(completions)
    assert raw_path not in repr(completions)


def test_http_failure_never_records_raw_exception_text() -> None:
    """A failing request exports only a stable error status, never exception text."""
    secret = "sk-sensitive-value"
    with capture_observability() as capture:
        with pytest.raises(RuntimeError):
            TestClient(
                _make_failing_app(secret), raise_server_exceptions=True
            ).get("/boom")

    server = next(
        span
        for span in capture.span_exporter.get_finished_spans()
        if span.kind is SpanKind.SERVER
    )
    assert server.status.status_code is StatusCode.ERROR
    assert server.status.description == "internal_error"
    assert server.attributes is not None
    assert server.attributes["http.response.status_code"] == 500
    assert secret not in repr(server.attributes)
    assert secret not in repr(server.events)
