"""v2 Router and Selector API (E5-S1, E5-S2, E5-S4).

Uses typed Pydantic request models (matching the majority pattern of sibling
``/v2`` POST endpoints — see ``backend/api/routers/patches.py``,
``validation.py``, ``jobs.py``, ``plans.py``) rather than a raw
``dict[str, Any]`` body: FastAPI validates the shape (including nested
objects) before the handler runs, so a malformed request (e.g. a ``null``
where an object is expected) is rejected with a structured 422 by the
framework itself, instead of requiring hand-written defensive parsing.

E5-S4: ``POST /v2/select`` looks up the routing policy's currently *promoted*
:class:`~backend.routing.contract.ScoreSnapshot` (via
:class:`~backend.routing.feedback.RoutingFeedbackService`) and forwards it to
the Selector, closing the feedback loop — a snapshot published and promoted
through ``POST /v2/evals/{namespace}/{name}/publish`` changes subsequent
``/v2/select`` decisions without any other client-visible change.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.agents.registry_v2 import AgentRegistry
from backend.api.routers.agents_v2 import get_agent_registry
from backend.persistence.database import get_store
from backend.routing.contract import (
    ContextDigest,
    ContextSignals,
    RouteConstraints,
    RouteDecision,
    RouteInput,
    RouteRequest,
    ScoreSnapshot,
    SelectBudget,
    SelectRequest,
)
from backend.routing.feedback import RoutingFeedbackService
from backend.routing.policy import default_routing_policy
from backend.routing.selector import NoEligibleAgentError
from backend.routing.service import RoutingService

logger = logging.getLogger(__name__)

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


def get_routing_feedback_service() -> RoutingFeedbackService:
    """Build the Routing Feedback Service dependency for request handlers (E5-S4).

    Returns:
        A new :class:`RoutingFeedbackService` bound to the default durable
        store — the same store ``POST /v2/evals/{namespace}/{name}/publish``
        promotes snapshots against, so a promotion is immediately visible here
        (both share the process-wide cached store).
    """
    return RoutingFeedbackService(get_store())


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


class RouteConstraintsBody(BaseModel):
    """Request body for :class:`backend.routing.contract.RouteConstraints`."""

    max_cost_usd: float = 0.05
    latency_class: str = "interactive"


class RouteDecisionBody(BaseModel):
    """Request body for the ``route`` field of a ``SelectRequest`` (reference §9.2)."""

    schemaVersion: str = "1.0"
    task_type: str
    intent: str
    path: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    constraints: RouteConstraintsBody = Field(default_factory=RouteConstraintsBody)
    rationale: str = ""


class SelectBudgetBody(BaseModel):
    """Request body for :class:`backend.routing.contract.SelectBudget`.

    ``0`` in any field means unconstrained for that dimension (see
    :mod:`backend.routing.selector`).
    """

    tokens: int = 0
    cost_usd: float = 0.0
    time_s: int = 0


class SelectRequestBody(BaseModel):
    """Request body for ``POST /v2/select`` (reference §9.2 ``SelectRequest``)."""

    schemaVersion: str = "1.0"
    route: RouteDecisionBody
    required_capabilities: list[str] = Field(default_factory=list)
    budget: SelectBudgetBody = Field(default_factory=SelectBudgetBody)


@router.post("/select")
def select_request(
    body: SelectRequestBody,
    service: RoutingService = Depends(get_routing_service),
    registry: AgentRegistry = Depends(get_agent_registry),
    feedback: RoutingFeedbackService = Depends(get_routing_feedback_service),
) -> dict[str, Any]:
    """Select an agent/model/strategy for a routed task.

    Looks up whatever :class:`~backend.routing.contract.ScoreSnapshot` is
    currently promoted for the platform default routing policy (E5-S4) and
    forwards it to the Selector's ``score-weighted`` stage — a snapshot
    published and promoted via ``POST /v2/evals/{namespace}/{name}/publish``
    changes this decision on the next call, with no other client-visible
    change (the closed feedback loop, reference §9.5).

    Args:
        body: A ``SelectRequest`` document (reference §9.2).
        service: Routing service dependency.
        registry: Agent Registry dependency, synced with enabled plugins
            before matching (same convention as ``GET /v2/agents/catalog``).
        feedback: Routing Feedback Service dependency, used to fetch the
            active score snapshot (if any) for the default routing policy.

    Returns:
        A ``SelectDecision`` document as JSON.

    Raises:
        HTTPException: 422 if no registered agent satisfies the request's
            ``required_capabilities`` under the active selector policy.
    """
    registry.sync_from_plugin_store()
    req = _to_select_request(body)
    scores = _get_active_snapshot_or_none(feedback, default_routing_policy().id)
    try:
        decision = service.select(req, registry=registry, scores=scores)
    except NoEligibleAgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "schemaVersion": decision.schema_version,
        "agent_id": decision.agent_id,
        "agent_version": decision.agent_version,
        "model": decision.model,
        "reasoning_strategy": decision.reasoning_strategy,
        "budget": {
            "tokens": decision.budget.tokens,
            "cost_usd": decision.budget.cost_usd,
            "time_s": decision.budget.time_s,
        },
        "fallbacks": [
            {
                "agent_id": fallback.agent_id,
                "model": fallback.model,
                "reasoning_strategy": fallback.reasoning_strategy,
            }
            for fallback in decision.fallbacks
        ],
        "score_basis": decision.score_basis,
    }


def _to_select_request(body: SelectRequestBody) -> SelectRequest:
    """Convert a validated :class:`SelectRequestBody` into the domain contract.

    Args:
        body: The validated request body.

    Returns:
        The equivalent :class:`SelectRequest`.
    """
    route = RouteDecision(
        schema_version=body.route.schemaVersion,
        task_type=body.route.task_type,
        intent=body.route.intent,
        path=tuple(body.route.path),
        confidence=body.route.confidence,
        constraints=RouteConstraints(
            max_cost_usd=body.route.constraints.max_cost_usd,
            latency_class=body.route.constraints.latency_class,
        ),
        rationale=body.route.rationale,
    )
    return SelectRequest(
        schema_version=body.schemaVersion,
        route=route,
        required_capabilities=tuple(body.required_capabilities),
        budget=SelectBudget(
            tokens=body.budget.tokens,
            cost_usd=body.budget.cost_usd,
            time_s=body.budget.time_s,
        ),
    )


def _get_active_snapshot_or_none(feedback: RoutingFeedbackService, policy_id: str) -> ScoreSnapshot | None:
    """Look up the active score snapshot for a policy id, degrading to ``None`` on failure.

    ``scores=None`` is already a fully valid, documented state for
    :meth:`~backend.routing.selector.Selector.select` (the ``score-weighted``
    stage is a no-op passthrough without one) — a snapshot-store read failure
    or a corrupted persisted document (E5-S4) should degrade ``/v2/select``
    back to that same no-op behavior rather than turning an otherwise-healthy
    selection request into an unrelated 500.

    Args:
        feedback: Routing Feedback Service to query.
        policy_id: Routing policy id whose active snapshot to fetch.

    Returns:
        The active :class:`~backend.routing.contract.ScoreSnapshot`, or
        ``None`` if none is active or the lookup failed.
    """
    try:
        return feedback.get_active_snapshot(policy_id)
    except Exception:  # noqa: BLE001 - defensive: never let a snapshot-lookup failure break /v2/select
        logger.warning("failed to fetch active score snapshot for policy %r; selecting without one", policy_id)
        return None


__all__ = ["get_routing_service", "router"]
