"""Prometheus metrics endpoint and middleware auto-attach.

The module-level ``router`` exposes ``GET /metrics`` with Prometheus
text-exposition output.

The module-level ``attach(app)`` callable installs
:class:`backend.observability.middleware.RequestTracingMiddleware` so the
U1 router-loader auto-wires the middleware when it discovers this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from backend.observability.middleware import attach as _attach_middleware
from backend.observability.middleware import get_registry

if TYPE_CHECKING:
    from fastapi import FastAPI

router = APIRouter(tags=["observability"])


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> str:
    """Return current metrics in Prometheus text-exposition format.

    Returns an empty (comment-only) body when no requests have been recorded.
    """
    return get_registry().prometheus_text()


def attach(app: "FastAPI") -> None:
    """Auto-attach the request-tracing middleware via the router-loader seam."""
    _attach_middleware(app)


__all__ = ["router", "attach"]
