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
