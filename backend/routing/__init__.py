"""Router and Selector extension points (epic E5, stories E5-S1, E5-S2).

This package delivers the E5-S1 Router story and the E5-S2 Selector story: a
typed, versioned contract for both pluggable extension points
(:mod:`backend.routing.contract`), the declarative routing policy model and
its YAML parser (:mod:`backend.routing.policy`, :mod:`backend.routing.policy_parsing`,
:mod:`backend.routing.selector_policy_parsing`), the rules-pipeline Router
executor (:mod:`backend.routing.router`), the Selector pipeline executor
(:mod:`backend.routing.selector`), and the tracing service
(:mod:`backend.routing.service`).

See ``docs/architecture/v2_platform_reference.md`` §9 for the full
specification and ``docs/routing/contract.md`` for the user-facing guide.
"""

from __future__ import annotations

from backend.routing.contract import (
    LATENCY_CLASSES,
    ROUTE_SCHEMA_VERSION,
    ROUTING_CONTRACT_HOST_API,
    SELECT_SCHEMA_VERSION,
    ContextDigest,
    ContextSignals,
    RouteConstraints,
    RouteDecision,
    RouteInput,
    RouteRequest,
    RouterPlugin,
    ScoreSnapshot,
    SelectBudget,
    SelectDecision,
    SelectFallback,
    SelectorPlugin,
    SelectRequest,
    TraceEvent,
)
from backend.routing.policy import (
    DEFAULT_ROUTING_POLICY_ID,
    FallbackPolicySpec,
    GuardrailsPolicySpec,
    RouteConstraintsSpec,
    RouterDefaultSpec,
    RouterEmbeddingsStageSpec,
    RouterLLMStageSpec,
    RouterPipelineSpec,
    RouterRuleSpec,
    RouterRulesStageSpec,
    RoutingPolicy,
    SelectorCapabilityMatchingStageSpec,
    SelectorCostAwareStageSpec,
    SelectorPipelineSpec,
    SelectorPolicySpec,
    SelectorScoreWeightedStageSpec,
    default_routing_policy,
)
from backend.routing.policy_parsing import (
    RoutingPolicyValidationResult,
    load_routing_policy,
    validate_routing_policy,
)
from backend.routing.router import EmbeddingsRouterStage, LLMRouterStage, Router
from backend.routing.selector import NoEligibleAgentError, Selector
from backend.routing.service import RoutingService

__all__ = [
    "ContextDigest",
    "ContextSignals",
    "DEFAULT_ROUTING_POLICY_ID",
    "EmbeddingsRouterStage",
    "FallbackPolicySpec",
    "GuardrailsPolicySpec",
    "LATENCY_CLASSES",
    "LLMRouterStage",
    "NoEligibleAgentError",
    "ROUTE_SCHEMA_VERSION",
    "ROUTING_CONTRACT_HOST_API",
    "RouteConstraints",
    "RouteConstraintsSpec",
    "RouteDecision",
    "RouteInput",
    "RouteRequest",
    "Router",
    "RouterDefaultSpec",
    "RouterEmbeddingsStageSpec",
    "RouterLLMStageSpec",
    "RouterPipelineSpec",
    "RouterPlugin",
    "RouterRuleSpec",
    "RouterRulesStageSpec",
    "RoutingPolicy",
    "RoutingPolicyValidationResult",
    "RoutingService",
    "SELECT_SCHEMA_VERSION",
    "ScoreSnapshot",
    "SelectBudget",
    "SelectDecision",
    "SelectFallback",
    "Selector",
    "SelectorCapabilityMatchingStageSpec",
    "SelectorCostAwareStageSpec",
    "SelectorPipelineSpec",
    "SelectorPlugin",
    "SelectorPolicySpec",
    "SelectorScoreWeightedStageSpec",
    "SelectRequest",
    "TraceEvent",
    "default_routing_policy",
    "load_routing_policy",
    "validate_routing_policy",
]
