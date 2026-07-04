"""In-process request metrics registry and Starlette/FastAPI middleware.

Tracks request counts and cumulative latency sums keyed by ``(method, path)``.
Assigns and propagates an ``X-Request-ID`` response header.
Logs one structured line per request via the stdlib ``logging`` module.

OpenTelemetry spans are emitted through ``backend.observability.tracing``.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from backend.observability.tracing import get_tracer

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class _RouteMetrics:
    count: int = 0
    latency_sum: float = 0.0
    errors: int = 0


class MetricsRegistry:
    """Thread-tolerant in-process counter/latency store."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], _RouteMetrics] = defaultdict(_RouteMetrics)

    def record(
        self,
        method: str,
        path: str,
        latency_seconds: float,
        status_code: int = 200,
    ) -> None:
        key = (method.upper(), path)
        entry = self._data[key]
        entry.count += 1
        entry.latency_sum += latency_seconds
        if status_code >= 500:
            entry.errors += 1

    def snapshot(self) -> dict[tuple[str, str], _RouteMetrics]:
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
        self._app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        method = scope.get("method", "GET")
        path = scope.get("path", "/")

        start = time.perf_counter()

        status_code: list[int] = [0]

        async def send_with_header(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
                status_code.append(message.get("status", 0))
            await send(message)

        tracer = get_tracer()
        with tracer.start_as_current_span(
            f"http.server {method} {path}",
            attributes={
                "http.request.method": method,
                "url.path": path,
                "autodev.request_id": request_id,
            },
        ) as span:
            await self._app(scope, receive, send_with_header)
            span.set_attribute("http.response.status_code", status_code[-1] if status_code else 0)

        elapsed = time.perf_counter() - start
        _registry.record(method, path, elapsed, status_code=status_code[-1] if status_code else 0)

        logger.info(
            "request completed",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "status": status_code[-1] if status_code else 0,
                "duration_s": round(elapsed, 6),
            },
        )


def attach(app: "FastAPI") -> None:
    """Add :class:`RequestTracingMiddleware` to *app*."""
    app.add_middleware(RequestTracingMiddleware)  # type: ignore[arg-type]


__all__ = [
    "MetricsRegistry",
    "RequestTracingMiddleware",
    "get_registry",
    "attach",
]
