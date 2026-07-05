"""``routing-policy.yaml`` data model and defaults (E5-S1).

A routing policy is a declarative, versioned document that governs how the
Router classifies a task and, in a later story (E5-S2), how the Selector
chooses an agent/model/strategy. See
``docs/architecture/v2_platform_reference.md`` §9.3 for the canonical (pt-BR)
specification this module implements.

This module holds the typed dataclasses and the built-in default policy. Raw
document parsing/validation (``validate_routing_policy``, ``load_routing_policy``,
and every ``_parse_*`` helper) lives in :mod:`backend.routing.policy_parsing`
— split out to keep both modules under the repository's file-size guideline.
That module depends on this one (for the dataclass types), not the reverse,
so there is no import cycle.

This module also has no dependency on :mod:`backend.routing.contract` (which
imports :class:`RoutingPolicy` from here) to avoid a circular import, mirroring
the split between :mod:`backend.reasoning.policy` and
:mod:`backend.reasoning.contract`.

Only the ``router:`` section's ``rules`` stage is fully implemented in E5-S1.
The ``embeddings`` and ``llm-router`` stage kinds are parsed into typed specs
but executed as pluggable stubs (see :mod:`backend.routing.router`). The
``selector:``, ``guardrails:``, and ``fallback:`` top-level sections are parsed
into thin placeholder dataclasses — unused this story, but present so E5-S2
can extend the *same* :class:`RoutingPolicy` object without a field rename.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Valid values for :attr:`RouteConstraintsSpec.latency_class`, per reference §9.2.
VALID_LATENCY_CLASSES = frozenset({"interactive", "batch"})

#: Valid ``kind`` values for a router pipeline stage, per reference §9.3.
VALID_ROUTER_STAGE_KINDS = frozenset({"rules", "embeddings", "llm-router"})


@dataclass(frozen=True)
class RouteConstraintsSpec:
    """Declarative default constraints applied to a :class:`RouteDecision`.

    Attributes:
        max_cost_usd: Maximum cost in US dollars the routed path may incur.
        latency_class: One of :data:`VALID_LATENCY_CLASSES`.
    """

    max_cost_usd: float = 0.05
    latency_class: str = "interactive"


@dataclass(frozen=True)
class RouterRuleSpec:
    """A single declarative ``when``/``set`` rule in a ``rules`` pipeline stage.

    Attributes:
        when: Predicate mapping of dotted signal name to an expected literal
            or an operator expression (e.g. ``">=high"``, ``"~=/pattern/"``).
            Every entry must match for the rule to fire (logical AND).
        set: Fields to set on the resulting decision — ``task_type`` and
            ``path`` are required; ``intent`` and ``constraints`` are
            optional and fall back to policy-level defaults when absent.
        confidence: Confidence assigned to a match, in ``[0, 1]``.
    """

    when: dict[str, Any]
    set: dict[str, Any]
    confidence: float = 1.0


@dataclass(frozen=True)
class RouterRulesStageSpec:
    """A ``kind: rules`` pipeline stage: ordered, first-match-wins predicates.

    Attributes:
        confidence_floor: Minimum confidence required to short-circuit the
            pipeline at this stage; a match below the floor cascades to the
            next stage.
        rules: Ordered rules, evaluated first-match-wins.
    """

    confidence_floor: float
    rules: tuple[RouterRuleSpec, ...] = ()


@dataclass(frozen=True)
class RouterEmbeddingsStageSpec:
    """A ``kind: embeddings`` pipeline stage (pgvector/E7 extension point stub).

    Not executed in E5-S1 — see :mod:`backend.routing.router` for the stub
    that raises :class:`NotImplementedError` if this stage is reached.

    Attributes:
        dataset: Labeled-examples dataset reference (e.g. ``"ns/intents@2026-06"``).
        threshold: Minimum similarity score to accept a classification.
    """

    dataset: str
    threshold: float


@dataclass(frozen=True)
class RouterLLMStageSpec:
    """A ``kind: llm-router`` pipeline stage (LLM-as-router extension point stub).

    Not executed in E5-S1 — see :mod:`backend.routing.router` for the stub
    that raises :class:`NotImplementedError` if this stage is reached.

    Attributes:
        model: Provider/model identifier used to classify intent.
        max_cost_usd: Budget ceiling for a single classification call.
        only_if_confidence_below: Only invoked when prior stages resolved
            below this confidence.
    """

    model: str
    max_cost_usd: float
    only_if_confidence_below: float


#: A single parsed router pipeline stage of any kind.
RouterStageSpec = RouterRulesStageSpec | RouterEmbeddingsStageSpec | RouterLLMStageSpec


@dataclass(frozen=True)
class RouterDefaultSpec:
    """The decision returned when no pipeline stage resolves a match.

    Generalizes the v1 ``_FULL_ORDER`` fallback (`backend/orchestrator/routing.py`)
    for unmapped run types into the declarative policy model.

    Attributes:
        task_type: Fallback task type.
        intent: Fallback intent.
        path: Fallback execution path (node/agent names).
        confidence: Confidence of the fallback decision (typically ``0.0``).
        rationale: Human-readable explanation of the fallback.
    """

    task_type: str
    intent: str
    path: tuple[str, ...]
    confidence: float = 0.0
    rationale: str = "no pipeline stage matched; using the policy default"


@dataclass(frozen=True)
class RouterPipelineSpec:
    """The ``router:`` section of a routing policy.

    Attributes:
        stages: Ordered pipeline stages, evaluated with short-circuit by
            confidence (reference §9.3).
        default: Fallback decision used when no stage resolves a match.
        constraints: Default constraints applied when a matched rule does not
            set its own ``constraints``.
    """

    stages: tuple[RouterStageSpec, ...]
    default: RouterDefaultSpec
    constraints: RouteConstraintsSpec = field(default_factory=RouteConstraintsSpec)


@dataclass(frozen=True)
class SelectorPolicySpec:
    """Placeholder for the ``selector:`` section — unused in E5-S1.

    Parsed but not structurally validated; E5-S2 defines the typed shape and
    replaces this placeholder's internals without renaming the
    :attr:`RoutingPolicy.selector` field.

    Attributes:
        raw: Original parsed ``selector`` mapping, or ``{}`` if absent.
    """

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GuardrailsPolicySpec:
    """Placeholder for the ``guardrails:`` section — unused in E5-S1.

    Attributes:
        raw: Original parsed ``guardrails`` mapping, or ``{}`` if absent.
    """

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FallbackPolicySpec:
    """Placeholder for the ``fallback:`` section — unused in E5-S1.

    Attributes:
        raw: Original parsed ``fallback`` mapping, or ``{}`` if absent.
    """

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingPolicy:
    """Fully parsed and validated ``routing-policy.yaml`` document.

    Attributes:
        schema_version: Policy schema version.
        id: Fully qualified policy id in ``namespace/name`` format.
        version: SemVer version of the policy.
        host_api: Supported host API version range.
        router: The Router's declarative pipeline (fully implemented this story).
        selector: Placeholder for the Selector's pipeline (E5-S2).
        guardrails: Placeholder for input/output guardrails (E5 later stories).
        fallback: Placeholder for cascade-fallback behavior (E5 later stories).
        raw: Original parsed policy document.
    """

    schema_version: str
    id: str
    version: str
    host_api: str
    router: RouterPipelineSpec
    selector: SelectorPolicySpec = field(default_factory=SelectorPolicySpec)
    guardrails: GuardrailsPolicySpec = field(default_factory=GuardrailsPolicySpec)
    fallback: FallbackPolicySpec = field(default_factory=FallbackPolicySpec)
    raw: dict[str, Any] = field(default_factory=dict)


def generic_router_default() -> RouterDefaultSpec:
    """Return the library-level generic fallback decision.

    Generalizes the v1 ``_FULL_ORDER`` (`backend/orchestrator/routing.py`)
    used for unmapped run types. Shared by :mod:`backend.routing.policy_parsing`
    (as the fallback when a document omits ``router.default``) and by
    :func:`default_routing_policy` below.

    Returns:
        A :class:`RouterDefaultSpec` routing to the full agent pipeline.
    """
    return RouterDefaultSpec(
        task_type="existing-repo-change",
        intent="unspecified",
        path=("navigator", "analyzer", "architect", "coder", "devops", "validator", "responder"),
        confidence=0.0,
        rationale="no pipeline stage matched; falling back to the full agent pipeline",
    )


DEFAULT_ROUTING_POLICY_ID = "autodev/routing-policy-default"


def default_routing_policy() -> RoutingPolicy:
    """Build a permissive default routing policy.

    Seeds a single ``rules`` stage with declarative rules that express the
    same intents as the v1 precursor's hardcoded ``_ROUTE_MAP``
    (`backend/orchestrator/routing.py`) — documentation updates,
    validation-only runs, and DevOps changes — plus the generic full-pipeline
    fallback for everything else.

    Returns:
        A ready-to-use :class:`RoutingPolicy`.
    """
    rules = (
        RouterRuleSpec(
            when={"input.text": r"~=/(?i)\b(doc|readme|changelog)\b/"},
            set={
                "task_type": "documentation-update",
                "intent": "docs",
                "path": ["navigator", "analyzer", "responder"],
            },
        ),
        RouterRuleSpec(
            when={"context.signals.has_tests": True, "intent": "validate"},
            set={
                "task_type": "validation-only",
                "intent": "validate",
                "path": ["navigator", "validator", "responder"],
            },
        ),
        RouterRuleSpec(
            when={"intent": "devops"},
            set={
                "task_type": "devops-change",
                "intent": "devops",
                "path": ["navigator", "analyzer", "devops", "responder"],
            },
        ),
    )
    return RoutingPolicy(
        schema_version="1",
        id=DEFAULT_ROUTING_POLICY_ID,
        version="1.0.0",
        host_api=">=2.0 <3.0",
        router=RouterPipelineSpec(
            stages=(RouterRulesStageSpec(confidence_floor=0.0, rules=rules),), default=generic_router_default()
        ),
    )


__all__ = [
    "DEFAULT_ROUTING_POLICY_ID",
    "FallbackPolicySpec",
    "GuardrailsPolicySpec",
    "RouteConstraintsSpec",
    "RouterDefaultSpec",
    "RouterEmbeddingsStageSpec",
    "RouterLLMStageSpec",
    "RouterPipelineSpec",
    "RouterRuleSpec",
    "RouterRulesStageSpec",
    "RouterStageSpec",
    "RoutingPolicy",
    "SelectorPolicySpec",
    "VALID_LATENCY_CLASSES",
    "VALID_ROUTER_STAGE_KINDS",
    "default_routing_policy",
    "generic_router_default",
]
