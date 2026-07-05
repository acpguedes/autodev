"""Typed Router contract (E5-S1).

Defines the versioned, SemVer-stable surface a Router plugin implements at the
``router`` extension point (:class:`backend.plugins.catalog.ExtensionPointKind.ROUTER`):
the ``RouteRequest``/``RouteDecision`` data contract and the ``RouterPlugin``
Protocol.

See ``docs/architecture/v2_platform_reference.md`` §9.1-9.3 for the canonical
(pt-BR) specification this module implements, and RFC-004/ADR-008 for the
design decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from backend.routing.policy import VALID_LATENCY_CLASSES, RoutingPolicy

#: Compatibility range this contract module implements. Bump only on a
#: breaking (MAJOR) change to the dataclasses/Protocols below.
ROUTING_CONTRACT_HOST_API = ">=2.0 <3.0"

#: ``schemaVersion`` stamped on every :class:`RouteRequest`/:class:`RouteDecision`
#: this module constructs, per reference §9.2.
ROUTE_SCHEMA_VERSION = "1.0"

#: Valid values for :attr:`RouteConstraints.latency_class`, per reference §9.2.
#: Re-exported from :mod:`backend.routing.policy` (single source of truth —
#: the policy module already defines this set for ``RouteConstraintsSpec``).
LATENCY_CLASSES = VALID_LATENCY_CLASSES


@dataclass(frozen=True)
class TraceEvent:
    """A single ordered step in a routing decision's trace.

    Deliberately identical in shape to :class:`backend.reasoning.contract.TraceEvent`
    but defined locally rather than imported — see ADR-008 for why the Router
    does not depend on the Reasoning Engine's contract module (the Router sits
    upstream of Reasoning in the pipeline; the reverse dependency would be
    backwards and would couple E5 to E4's module boundary unnecessarily).

    Attributes:
        sequence: Monotonically increasing position of this event, or ``-1``
            for a service-level event not tied to a specific pipeline stage
            (mirrors :class:`backend.reasoning.service.ReasoningService`'s
            convention).
        name: Dotted event name (``domain.entity.action``), e.g.
            ``"router.decision.recorded"``.
        payload: Event-specific structured data.
        timestamp: Unix timestamp (seconds) the event was emitted at.
    """

    sequence: int
    name: str
    payload: dict[str, Any]
    timestamp: float


@dataclass(frozen=True)
class ContextSignals:
    """Repository/session signals summarized by the Context/RAG Service (E7).

    Attributes:
        has_tests: Whether the repository under change has a test suite.
        languages: Programming languages detected in the repository.
    """

    has_tests: bool = False
    languages: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextDigest:
    """Optional context summary attached to a :class:`RouteRequest`.

    Attributes:
        repo: Repository identifier or path.
        signals: Structured signals about the repository/session.
    """

    repo: str = ""
    signals: ContextSignals = field(default_factory=ContextSignals)


@dataclass(frozen=True)
class RouteInput:
    """The user/trigger input a :class:`RouteRequest` carries.

    Attributes:
        text: Free-text task description or user message.
        attachments: URIs of any attachments accompanying the input.
    """

    text: str
    attachments: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteRequest:
    """Immutable request handed to a :class:`RouterPlugin` for classification.

    Attributes:
        schema_version: Contract schema version, e.g. ``"1.0"``.
        session_id: Identifier of the session this request belongs to.
        run_id: Identifier of the run this request belongs to.
        input: The user/trigger input to classify.
        context_digest: Optional repository/session context summary (E7).
    """

    schema_version: str
    session_id: str
    run_id: str
    input: RouteInput
    context_digest: ContextDigest | None = None


@dataclass(frozen=True)
class RouteConstraints:
    """Cost/latency constraints attached to a :class:`RouteDecision`.

    Attributes:
        max_cost_usd: Maximum cost in US dollars the routed path may incur.
        latency_class: One of :data:`LATENCY_CLASSES`.
    """

    max_cost_usd: float
    latency_class: str


@dataclass(frozen=True)
class RouteDecision:
    """The outcome of routing a task: its type, path, and justification.

    Attributes:
        schema_version: Contract schema version, e.g. ``"1.0"``.
        task_type: Classified task type, e.g. ``"existing-repo-change"``.
        intent: Classified intent, e.g. ``"fix-bug"``, ``"add-feature"``.
        path: Suggested execution path (Flow/E3 node or agent names, in order).
        confidence: Confidence of the classification, in ``[0, 1]``.
        constraints: Cost/latency constraints for the routed path.
        rationale: Human-readable justification, kept separate from any
            machine-readable metadata (repository working-style convention).
    """

    schema_version: str
    task_type: str
    intent: str
    path: tuple[str, ...]
    confidence: float
    constraints: RouteConstraints
    rationale: str


class RouterPlugin(Protocol):
    """Pluggable Router contract (extension point ``router``, reference §9.2).

    A conforming implementation classifies a :class:`RouteRequest` into a
    :class:`RouteDecision` under a given :class:`RoutingPolicy`. Unlike the
    Reasoning Strategy contract (ADR-007), this Protocol is synchronous: the
    NF target is p95 < 150 ms for a deterministic, in-process classification
    (reference §9.7) — there is no LLM/tool mediation to await on the primary
    (``rules``) path.

    ``context`` is an additive extension over the reference's illustrated
    two-parameter signature (reference §9.2 summarizes the interface; it is
    not an exhaustive wire spec): it carries caller-supplied signals not yet
    modeled on :class:`RouteRequest` (e.g. an upstream classifier's ``intent``
    hint). Every implementation — including third-party ones — must accept it
    (with a ``None`` default) so :class:`~backend.routing.service.RoutingService`
    can forward it uniformly without special-casing any particular
    implementation (see ADR-008).
    """

    def route(
        self,
        req: RouteRequest,
        policy: RoutingPolicy,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> RouteDecision:
        """Classify a request into a routed decision under a policy.

        Args:
            req: The request to classify.
            policy: The routing policy in effect (pipeline, default, constraints).
            context: Additional caller-supplied signals layered on top of
                ``req`` (e.g. an intent hint); implementations that do not use
                extra signals may ignore this parameter.

        Returns:
            The resulting :class:`RouteDecision`.
        """
        ...


__all__ = [
    "ContextDigest",
    "ContextSignals",
    "LATENCY_CLASSES",
    "ROUTE_SCHEMA_VERSION",
    "ROUTING_CONTRACT_HOST_API",
    "RouteConstraints",
    "RouteDecision",
    "RouteInput",
    "RouteRequest",
    "RouterPlugin",
    "TraceEvent",
]
