"""Routing service: policy-driven classification and selection with a decision trace (E5-S1, E5-S2).

Ties a :class:`~backend.routing.contract.RouterPlugin` and a
:class:`~backend.routing.contract.SelectorPlugin` to a
:class:`~backend.routing.policy.RoutingPolicy` and records every
:class:`~backend.routing.contract.RouteDecision`/:class:`~backend.routing.contract.SelectDecision`
to the trace sink, mirroring :class:`backend.reasoning.service.ReasoningService`'s
shape. Router and Selector tracing share the same ``_emit`` plumbing rather
than each maintaining its own (E5-S2 extends this service instead of adding a
sibling ``SelectorService`` to avoid duplicating it).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from backend.agents.registry_v2 import AgentRegistry
from backend.routing.contract import (
    RouteDecision,
    RouteRequest,
    RouterPlugin,
    ScoreSnapshot,
    SelectDecision,
    SelectorPlugin,
    SelectRequest,
    TraceEvent,
)
from backend.routing.policy import RoutingPolicy
from backend.routing.router import Router
from backend.routing.selector import Selector


class RoutingService:
    """Classifies requests, selects candidates, and traces the resulting decisions."""

    def __init__(
        self,
        policy: RoutingPolicy,
        *,
        router: RouterPlugin | None = None,
        selector: SelectorPlugin | None = None,
        on_event: Callable[[TraceEvent], None] | None = None,
    ) -> None:
        """Initialize the service with a policy and optional router/selector/tracer.

        Args:
            policy: The routing policy in force.
            router: The Router plugin to classify with; defaults to a fresh
                rules-only :class:`~backend.routing.router.Router`.
            selector: The Selector plugin to choose candidates with; defaults
                to a fresh :class:`~backend.routing.selector.Selector`.
            on_event: Trace sink; receives one event per recorded decision.
        """
        self._policy = policy
        self._router: RouterPlugin = router if router is not None else Router()
        self._selector: SelectorPlugin = selector if selector is not None else Selector()
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

    def select(
        self,
        req: SelectRequest,
        *,
        registry: AgentRegistry,
        scores: ScoreSnapshot | None = None,
    ) -> SelectDecision:
        """Select an agent/model/strategy under the service's policy and trace it.

        Args:
            req: The request to resolve (route decision, required capabilities,
                run budget).
            registry: Agent Registry (E2) to match ``required_capabilities``
                against; a per-call parameter (not stored) so the Selector
                stays stateless, mirroring :class:`~backend.routing.router.Router`.
            scores: Optional Evaluation Service score snapshot (E5-S4).

        Returns:
            The resulting :class:`SelectDecision`.
        """
        decision = self._selector.select(req, self._policy, registry, scores)
        self._emit(
            "selector.decision.recorded",
            {
                "task_type": req.route.task_type,
                "intent": req.route.intent,
                "required_capabilities": list(req.required_capabilities),
                "agent_id": decision.agent_id,
                "agent_version": decision.agent_version,
                "model": decision.model,
                "reasoning_strategy": decision.reasoning_strategy,
                "fallbacks": [fallback.agent_id for fallback in decision.fallbacks],
                "score_basis": decision.score_basis,
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
