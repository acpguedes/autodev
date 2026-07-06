"""Typed Router and Selector contract (E5-S1, E5-S2).

Defines the versioned, SemVer-stable surface a Router plugin implements at the
``router`` extension point (:class:`backend.plugins.catalog.ExtensionPointKind.ROUTER`):
the ``RouteRequest``/``RouteDecision`` data contract and the ``RouterPlugin``
Protocol. Also defines the analogous ``SelectRequest``/``SelectDecision`` data
contract and the ``SelectorPlugin`` Protocol for the ``selector`` extension
point (E5-S2), fixed by RFC-004 alongside the Router contract.

See ``docs/architecture/v2_platform_reference.md`` §9.1-9.3 for the canonical
(pt-BR) specification this module implements, and RFC-004/ADR-008 for the
design decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from backend.agents.registry_v2 import AgentRegistry
from backend.routing.policy import VALID_LATENCY_CLASSES, RoutingPolicy

#: Compatibility range this contract module implements. Bump only on a
#: breaking (MAJOR) change to the dataclasses/Protocols below.
ROUTING_CONTRACT_HOST_API = ">=2.0 <3.0"

#: ``schemaVersion`` stamped on every :class:`RouteRequest`/:class:`RouteDecision`
#: this module constructs, per reference §9.2.
ROUTE_SCHEMA_VERSION = "1.0"

#: ``schemaVersion`` stamped on every :class:`SelectRequest`/:class:`SelectDecision`
#: this module constructs, per reference §9.2.
SELECT_SCHEMA_VERSION = "1.0"

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


@dataclass(frozen=True)
class SelectBudget:
    """Resource ceiling shared by :class:`SelectRequest` and :class:`SelectDecision`.

    Shape mirrors reference §9.2's ``{tokens, cost_usd, time_s}`` budget map,
    distinct from :class:`backend.reasoning.contract.Budget` (which splits
    tokens differently and uses milliseconds) — see
    :mod:`backend.routing.selector` for how a candidate's
    :class:`backend.agents.manifest.AgentBudgets` is mapped onto this shape.

    Attributes:
        tokens: Maximum total tokens (input + output) allowed. ``0`` means
            unconstrained for this dimension (see :mod:`backend.routing.selector`).
        cost_usd: Maximum cost in US dollars allowed. ``0`` means unconstrained.
        time_s: Maximum wall-clock duration allowed, in seconds. ``0`` means
            unconstrained.
    """

    tokens: int
    cost_usd: float
    time_s: int


@dataclass(frozen=True)
class SelectRequest:
    """Immutable request handed to a :class:`SelectorPlugin` to choose a candidate.

    Attributes:
        schema_version: Contract schema version, e.g. ``"1.0"``.
        route: The :class:`RouteDecision` produced by the Router for this run.
        required_capabilities: Capability ids the chosen agent must declare
            (matched against the Agent Registry, E2).
        budget: The run's own budget ceiling. Tenant quotas (E11) are out of
            scope for E5-S2 and are not represented here — see
            :mod:`backend.routing.selector`'s module docstring.
    """

    schema_version: str
    route: RouteDecision
    required_capabilities: tuple[str, ...]
    budget: SelectBudget


@dataclass(frozen=True)
class SelectFallback:
    """A single cascade-fallback candidate carried on a :class:`SelectDecision`.

    Attributes:
        agent_id: Fully qualified agent id of the fallback candidate.
        model: Provider/model identifier for the fallback candidate.
        reasoning_strategy: Reasoning Strategy (E4) id for the fallback candidate.
    """

    agent_id: str
    model: str
    reasoning_strategy: str


@dataclass(frozen=True)
class SelectDecision:
    """The outcome of selecting an agent/model/strategy for a routed task.

    Attributes:
        schema_version: Contract schema version, e.g. ``"1.0"``.
        agent_id: Fully qualified id (E2) of the chosen agent.
        agent_version: SemVer version of the chosen agent registration.
        model: Provider/model identifier the chosen agent should run under.
        reasoning_strategy: Reasoning Strategy (E4) id the chosen agent should run under.
        budget: Resolved budget ceiling for this run of the chosen agent.
        fallbacks: Ordered cascade-fallback candidates, most-preferred first.
        score_basis: Id of the Evaluation Service score snapshot considered for
            this decision, or ``""`` when none was supplied (E5-S4 wires a real
            snapshot store in; see :mod:`backend.routing.selector`).
    """

    schema_version: str
    agent_id: str
    agent_version: str
    model: str
    reasoning_strategy: str
    budget: SelectBudget
    fallbacks: tuple[SelectFallback, ...] = ()
    score_basis: str = ""


@dataclass(frozen=True)
class ScoreSnapshot:
    """Typed placeholder for an Evaluation Service score snapshot (E5-S4).

    E5-S4 is responsible for publishing real, versioned snapshots from the
    Evaluation Service (:mod:`backend.evals`) and wiring them into the
    ``score-weighted`` selector stage. This minimal shape exists only so the
    :class:`SelectorPlugin` Protocol and the selector pipeline can be typed
    against a stable parameter today; :mod:`backend.routing.selector` treats
    the ``score-weighted`` stage as a no-op passthrough regardless of whether
    a snapshot is supplied.

    Attributes:
        schema_version: Contract schema version, e.g. ``"1.0"``.
        snapshot_id: Identifier of this score snapshot (becomes a
            :class:`SelectDecision`'s ``score_basis`` when supplied).
        scores: Mapping of ``agent_id`` (or ``agent_id@version``) to a scalar
            quality/blended score. Fields and shape are provisional — E5-S4
            may extend or replace them.
    """

    schema_version: str
    snapshot_id: str
    scores: dict[str, float] = field(default_factory=dict)


class SelectorPlugin(Protocol):
    """Pluggable Selector contract (extension point ``selector``, reference §9.2).

    A conforming implementation matches a :class:`SelectRequest`'s
    ``required_capabilities`` against the Agent Registry (E2), applies the
    active :class:`~backend.routing.policy.RoutingPolicy`'s ``selector``
    pipeline (capability-matching, cost-aware, score-weighted, tie-breaker),
    and returns a :class:`SelectDecision`. Synchronous, mirroring
    :class:`RouterPlugin` (ADR-008): capability/cost-aware matching is
    in-process and I/O-light (registry reads only), with no LLM/tool mediation
    to await.
    """

    def select(
        self,
        req: SelectRequest,
        policy: RoutingPolicy,
        registry: AgentRegistry,
        scores: ScoreSnapshot | None = None,
    ) -> SelectDecision:
        """Choose an agent/model/strategy for a routed task.

        Args:
            req: The request to resolve (route decision, required capabilities,
                run budget).
            policy: The routing policy in effect, whose ``selector`` section
                configures the pipeline stages and tie-breaker.
            registry: Agent Registry (E2) to match ``required_capabilities``
                against.
            scores: Optional Evaluation Service score snapshot (E5-S4); ``None``
                until the closed feedback loop lands.

        Returns:
            The resulting :class:`SelectDecision`.
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
    "SELECT_SCHEMA_VERSION",
    "ScoreSnapshot",
    "SelectBudget",
    "SelectDecision",
    "SelectFallback",
    "SelectRequest",
    "SelectorPlugin",
    "TraceEvent",
]
