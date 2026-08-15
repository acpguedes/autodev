"""In-process request metrics registry and Starlette/FastAPI middleware.

Tracks request counts and cumulative latency sums keyed by route template.
Assigns and propagates an ``X-Request-ID`` response header.
Logs one structured line per request via the stdlib ``logging`` module.

OpenTelemetry spans and RED metrics use the runtime-owned three-signal APIs.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from opentelemetry import propagate
from opentelemetry.trace import SpanKind, Status, StatusCode

from backend.observability.context import (
    bind_correlation_context,
    sanitize_identifier,
)
from backend.observability.metrics import get_metric_sink
from backend.observability.runtime import get_tracer

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class _RouteMetrics:
    """Aggregate request counters for a single ``(method, path)`` route.

    Attributes:
        count: Total number of recorded requests.
        latency_sum: Cumulative request latency, in seconds.
        errors: Number of recorded requests with a 5xx status code.
    """

    count: int = 0
    latency_sum: float = 0.0
    errors: int = 0


class MetricsRegistry:
    """Thread-tolerant in-process counter/latency store."""

    def __init__(self) -> None:
        """Initialize an empty metrics registry."""
        self._data: dict[tuple[str, str], _RouteMetrics] = defaultdict(_RouteMetrics)

    def record(
        self,
        method: str,
        path: str,
        latency_seconds: float,
        status_code: int = 200,
    ) -> None:
        """Record a single completed request against its route's metrics.

        Args:
            method: HTTP method of the request.
            path: URL path of the request.
            latency_seconds: Observed request latency, in seconds.
            status_code: HTTP status code returned for the request.
        """
        key = (method.upper(), path)
        entry = self._data[key]
        entry.count += 1
        entry.latency_sum += latency_seconds
        if status_code >= 500:
            entry.errors += 1

    def snapshot(self) -> dict[tuple[str, str], _RouteMetrics]:
        """Return a shallow copy of the current per-route metrics.

        Returns:
            A mapping of ``(method, path)`` to its accumulated metrics.
        """
        return dict(self._data)

    def prometheus_text(self) -> str:
        """Render registry as Prometheus text-exposition format."""
        lines: list[str] = []
        lines.append("# HELP http_requests_total Total HTTP requests")
        lines.append("# TYPE http_requests_total counter")
        lines.append("# HELP http_request_duration_seconds Cumulative request duration")
        lines.append("# TYPE http_request_duration_seconds counter")
        lines.append("# HELP http_request_errors_total Total HTTP 5xx responses")
        lines.append("# TYPE http_request_errors_total counter")
        for (method, path), m in sorted(self._data.items()):
            label = f'method="{method}",path="{path}"'
            lines.append(f"http_requests_total{{{label}}} {m.count}")
            lines.append(f"http_request_duration_seconds{{{label}}} {m.latency_sum:.6f}")
            lines.append(f"http_request_errors_total{{{label}}} {m.errors}")
        return "\n".join(lines) + "\n" if lines else "# (no requests recorded)\n"


# Module-level singleton so all components share one registry.
_registry = MetricsRegistry()


def get_registry() -> MetricsRegistry:
    """Return the module-level metrics registry."""
    return _registry


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class RequestTracingMiddleware:
    """ASGI middleware that traces requests and records metrics."""

    def __init__(self, app: Callable) -> None:
        """Wrap an ASGI application with request tracing and metrics recording.

        Args:
            app: The wrapped ASGI application callable.
        """
        self._app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Invoke the wrapped ASGI app, tracing and recording metrics for HTTP requests.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive channel.
            send: ASGI send channel.
        """
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        carrier = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope.get("headers", [])
        }
        incoming_request_id = carrier.get("x-request-id", "").strip()
        request_id = (
            incoming_request_id
            if incoming_request_id
            and sanitize_identifier(incoming_request_id) == incoming_request_id
            else str(uuid.uuid4())
        )
        parent_context = propagate.extract(carrier)
        method = str(scope.get("method", "GET")).upper()
        started = time.perf_counter()
        response_status = 0

        async def send_with_header(message: dict) -> None:
            """Replace the response ``X-Request-ID`` with the correlated value."""
            nonlocal response_status
            if message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
                response_status = int(message.get("status", 0))
            await send(message)

        with bind_correlation_context(request_id=request_id):
            with get_tracer().start_as_current_span(
                f"{method} pending-route",
                context=parent_context,
                kind=SpanKind.SERVER,
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                try:
                    await self._app(scope, receive, send_with_header)
                except BaseException:
                    response_status = 500
                    span.set_status(Status(StatusCode.ERROR, "internal_error"))
                    raise
                finally:
                    route = _route_template(scope)
                    elapsed = time.perf_counter() - started
                    span.update_name(f"{method} {route}")
                    span.set_attributes(
                        _safe_http_attributes(
                            method=method,
                            route=route,
                            status_code=response_status,
                            request_id=request_id,
                        )
                    )
                    get_metric_sink().record_http_request(
                        method=method,
                        route=route,
                        status_code=response_status,
                        duration_seconds=elapsed,
                    )
                    _registry.record(
                        method,
                        route,
                        elapsed,
                        status_code=response_status,
                    )
                    logger.info(
                        "request completed",
                        extra={
                            "event": "http.request.completed",
                            "request_id": request_id,
                            "method": method,
                            "route": route,
                            "status": response_status,
                            "duration_s": round(elapsed, 6),
                        },
                    )


def _route_template(scope: dict) -> str:
    """Return the matched route template or a bounded fallback.

    Args:
        scope: ASGI HTTP scope populated by the application router.

    Returns:
        The matched route template, or ``"_unmatched"``.
    """
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else "_unmatched"


def _safe_http_attributes(
    *, method: str, route: str, status_code: int, request_id: str
) -> dict[str, str | int]:
    """Build the exact content-free HTTP server span attributes.

    Args:
        method: Normalized HTTP method.
        route: Matched route template or bounded fallback.
        status_code: HTTP response status code.
        request_id: Bounded request correlation identifier.

    Returns:
        Safe HTTP semantic and AutoDev correlation attributes.
    """
    return {
        "http.request.method": method,
        "http.route": route,
        "http.response.status_code": status_code,
        "autodev.request_id": request_id,
    }


def attach(app: "FastAPI") -> None:
    """Add :class:`RequestTracingMiddleware` to *app*."""
    app.add_middleware(RequestTracingMiddleware)  # type: ignore[arg-type]


__all__ = [
    "MetricsRegistry",
    "RequestTracingMiddleware",
    "get_registry",
    "attach",
]
