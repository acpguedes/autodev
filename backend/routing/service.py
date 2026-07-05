"""Routing service: policy-driven classification with a decision trace (E5-S1).

Ties a :class:`~backend.routing.contract.RouterPlugin` and a
:class:`~backend.routing.policy.RoutingPolicy` together and records every
:class:`~backend.routing.contract.RouteDecision` to the trace sink, mirroring
:class:`backend.reasoning.service.ReasoningService`'s shape.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from backend.routing.contract import RouteDecision, RouteRequest, RouterPlugin, TraceEvent
from backend.routing.policy import RoutingPolicy
from backend.routing.router import Router


class RoutingService:
    """Classifies requests and traces the resulting decision."""

    def __init__(
        self,
        policy: RoutingPolicy,
        *,
        router: RouterPlugin | None = None,
        on_event: Callable[[TraceEvent], None] | None = None,
    ) -> None:
        """Initialize the service with a policy and an optional router/tracer.

        Args:
            policy: The routing policy in force.
            router: The Router plugin to classify with; defaults to a fresh
                rules-only :class:`~backend.routing.router.Router`.
            on_event: Trace sink; receives one event per recorded decision.
        """
        self._policy = policy
        self._router: RouterPlugin = router if router is not None else Router()
        self._on_event = on_event

    def route(self, req: RouteRequest, *, context: Mapping[str, Any] | None = None) -> RouteDecision:
        """Classify ``req`` under the service's policy and trace the decision.

        Args:
            req: The request to classify.
            context: Additional signals layered on top of the request-derived
                ones, forwarded to the router unconditionally — every
                :class:`RouterPlugin` implementation accepts ``context`` (see
                ADR-008), so no implementation-specific dispatch is needed here.

        Returns:
            The resulting :class:`RouteDecision`.
        """
        decision = self._router.route(req, self._policy, context=context)
        self._emit(
            "router.decision.recorded",
            {
                "session_id": req.session_id,
                "run_id": req.run_id,
                "task_type": decision.task_type,
                "intent": decision.intent,
                "path": list(decision.path),
                "confidence": decision.confidence,
                "rationale": decision.rationale,
            },
        )
        return decision

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        """Emit a service-level decision event to the trace sink, if configured.

        Args:
            name: Dotted event name.
            payload: Structured payload for the event.
        """
        if self._on_event is not None:
            self._on_event(TraceEvent(sequence=-1, name=name, payload=payload, timestamp=time.time()))


__all__ = ["RoutingService"]
