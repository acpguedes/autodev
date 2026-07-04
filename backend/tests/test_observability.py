"""Tests for U17 observability (backend/observability/ + GET /metrics).

Coverage:
- Throwaway FastAPI app with attach() gets X-Request-ID header on responses.
- Counter increments after a request.
- GET /metrics on the real app returns 200 with text/plain content-type.
- /metrics returns 200 even when no requests have been made (zeroed/empty registry).
- /metrics output includes Prometheus comment headers.
- X-Request-ID is a valid UUID.
- Each request gets a distinct X-Request-ID.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.main import app as main_app
from backend.observability.middleware import MetricsRegistry, attach
from backend.observability.tracing import (
    InMemorySpanExporter,
    configure_tracing,
    step_span_attributes,
)
from backend.orchestrator.service import OrchestratorService
from backend.persistence.sqlite_adapter import SQLiteStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    """Build an isolated throwaway FastAPI app with the middleware attached."""
    _app = FastAPI()
    attach(_app)

    @_app.get("/ping")
    def ping() -> dict:
        return {"pong": True}

    return _app


# ---------------------------------------------------------------------------
# X-Request-ID header
# ---------------------------------------------------------------------------


def test_response_has_x_request_id_header() -> None:
    client = TestClient(_make_app())
    resp = client.get("/ping")
    assert "x-request-id" in resp.headers


def test_x_request_id_is_valid_uuid() -> None:
    client = TestClient(_make_app())
    resp = client.get("/ping")
    rid = resp.headers["x-request-id"]
    # Should not raise.
    parsed = uuid.UUID(rid)
    assert str(parsed) == rid


def test_each_request_gets_distinct_request_id() -> None:
    client = TestClient(_make_app())
    r1 = client.get("/ping")
    r2 = client.get("/ping")
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


# ---------------------------------------------------------------------------
# Counter increments
# ---------------------------------------------------------------------------


def test_counter_increments_after_request() -> None:
    # Use an isolated registry to avoid cross-test interference.
    registry = MetricsRegistry()

    _app = FastAPI()

    from backend.observability.middleware import RequestTracingMiddleware
    import backend.observability.middleware as _mw_module

    original_registry = _mw_module._registry
    _mw_module._registry = registry
    try:
        _app.add_middleware(RequestTracingMiddleware)  # type: ignore[arg-type]

        @_app.get("/count-me")
        def count_me() -> dict:
            return {}

        client = TestClient(_app)
        client.get("/count-me")
        snap = registry.snapshot()
        counts = {f"{m} {p}": v.count for (m, p), v in snap.items()}
        assert counts.get("GET /count-me", 0) >= 1
    finally:
        _mw_module._registry = original_registry


def test_error_counter_increments_for_500_response() -> None:
    registry = MetricsRegistry()
    registry.record("GET", "/boom", 0.01, status_code=500)

    text = registry.prometheus_text()

    assert 'http_request_errors_total{method="GET",path="/boom"} 1' in text


def test_step_span_attributes_exclude_content() -> None:
    attrs = step_span_attributes(
        run_id="run-1",
        step_id="navigator",
        agent="navigator",
        status="completed",
    )

    assert attrs == {
        "autodev.run_id": "run-1",
        "autodev.step_id": "navigator",
        "autodev.agent": "navigator",
        "autodev.status": "completed",
    }


def test_orchestrator_agent_step_emits_correlated_span(tmp_path) -> None:
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter, service_name="autodev-test")
    store = SQLiteStore(f"sqlite:///{tmp_path / 'trace.db'}")
    service = OrchestratorService(store=store, project_root=tmp_path)
    session = service.create_plan("Trace the workflow")

    run = service.handle_message(session.session_id, "validate the repo")

    step_spans = [
        span
        for span in exporter.get_finished_spans()
        if span.name.startswith("autodev.run.step.")
    ]
    assert step_spans
    attributes = step_spans[0].attributes
    assert attributes is not None
    assert attributes["autodev.run_id"] == run.run_id
    assert attributes["autodev.step_id"]


# ---------------------------------------------------------------------------
# GET /metrics on the real app
# ---------------------------------------------------------------------------


_main_client = TestClient(main_app)


def test_metrics_endpoint_returns_200() -> None:
    resp = _main_client.get("/metrics")
    assert resp.status_code == 200


def test_metrics_endpoint_content_type_is_text_plain() -> None:
    resp = _main_client.get("/metrics")
    assert "text/plain" in resp.headers["content-type"]


def test_metrics_endpoint_returns_200_with_empty_registry() -> None:
    """Even when no requests have been recorded, /metrics must return 200."""
    resp = _main_client.get("/metrics")
    assert resp.status_code == 200
    # Body is non-empty (at least has comment lines).
    assert len(resp.text) > 0


def test_metrics_output_contains_prometheus_comment() -> None:
    resp = _main_client.get("/metrics")
    # After at least the /metrics request itself, the body must mention HELP or no-requests comment.
    text = resp.text
    assert "#" in text
