"""v2 Router API (E5-S1).

Uses typed Pydantic request models (matching the majority pattern of sibling
``/v2`` POST endpoints — see ``backend/api/routers/patches.py``,
``validation.py``, ``jobs.py``, ``plans.py``) rather than a raw
``dict[str, Any]`` body: FastAPI validates the shape (including nested
objects) before the handler runs, so a malformed request (e.g. a ``null``
where an object is expected) is rejected with a structured 422 by the
framework itself, instead of requiring hand-written defensive parsing.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.routing.contract import ContextDigest, ContextSignals, RouteInput, RouteRequest
from backend.routing.policy import default_routing_policy
from backend.routing.service import RoutingService

router = APIRouter(prefix="/v2", tags=["routing"])


class ContextSignalsBody(BaseModel):
    """Request body for :class:`backend.routing.contract.ContextSignals`."""

    has_tests: bool = False
    languages: list[str] = Field(default_factory=list)


class ContextDigestBody(BaseModel):
    """Request body for :class:`backend.routing.contract.ContextDigest`."""

    repo: str = ""
    signals: ContextSignalsBody = Field(default_factory=ContextSignalsBody)


class RouteInputBody(BaseModel):
    """Request body for :class:`backend.routing.contract.RouteInput`."""

    text: str
    attachments: list[str] = Field(default_factory=list)


class RouteRequestBody(BaseModel):
    """Request body for ``POST /v2/route`` (reference §9.2 ``RouteRequest``)."""

    schemaVersion: str = "1.0"
    session_id: str = ""
    run_id: str = ""
    input: RouteInputBody
    context_digest: ContextDigestBody | None = None
    context: dict[str, Any] | None = None


def get_routing_service() -> RoutingService:
    """Build the routing service dependency for request handlers.

    Returns:
        A new :class:`RoutingService` bound to the platform default policy.
    """
    return RoutingService(default_routing_policy())


@router.post("/route")
def route_request(
    body: RouteRequestBody,
    service: RoutingService = Depends(get_routing_service),
) -> dict[str, Any]:
    """Classify a task and return its routed decision.

    Args:
        body: A ``RouteRequest`` document (reference §9.2). ``context`` is an
            additive, out-of-contract field carrying caller-supplied signals
            (e.g. an upstream ``intent`` hint) forwarded to the Router.
        service: Routing service dependency.

    Returns:
        A ``RouteDecision`` document as JSON.
    """
    req = _to_route_request(body)
    decision = service.route(req, context=body.context)
    return {
        "schemaVersion": decision.schema_version,
        "task_type": decision.task_type,
        "intent": decision.intent,
        "path": list(decision.path),
        "confidence": decision.confidence,
        "constraints": {
            "max_cost_usd": decision.constraints.max_cost_usd,
            "latency_class": decision.constraints.latency_class,
        },
        "rationale": decision.rationale,
    }


def _to_route_request(body: RouteRequestBody) -> RouteRequest:
    """Convert a validated :class:`RouteRequestBody` into the domain contract.

    Args:
        body: The validated request body.

    Returns:
        The equivalent :class:`RouteRequest`.
    """
    context_digest = None
    if body.context_digest is not None:
        context_digest = ContextDigest(
            repo=body.context_digest.repo,
            signals=ContextSignals(
                has_tests=body.context_digest.signals.has_tests,
                languages=tuple(body.context_digest.signals.languages),
            ),
        )
    return RouteRequest(
        schema_version=body.schemaVersion,
        session_id=body.session_id,
        run_id=body.run_id,
        input=RouteInput(text=body.input.text, attachments=tuple(body.input.attachments)),
        context_digest=context_digest,
    )


__all__ = ["get_routing_service", "router"]
