"""Router extension point (epic E5, story E5-S1).

This package delivers the E5-S1 story: a typed, versioned contract for the
pluggable Router (:mod:`backend.routing.contract`), the declarative routing
policy model and its YAML parser (:mod:`backend.routing.policy`,
:mod:`backend.routing.policy_parsing`), the rules-pipeline executor
(:mod:`backend.routing.router`), and the tracing service
(:mod:`backend.routing.service`).

See ``docs/architecture/v2_platform_reference.md`` §9 for the full
specification and ``docs/routing/contract.md`` for the user-facing guide.
"""

from __future__ import annotations

from backend.routing.contract import (
    LATENCY_CLASSES,
    ROUTE_SCHEMA_VERSION,
    ROUTING_CONTRACT_HOST_API,
    ContextDigest,
    ContextSignals,
    RouteConstraints,
    RouteDecision,
    RouteInput,
    RouteRequest,
    RouterPlugin,
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
    SelectorPolicySpec,
    default_routing_policy,
)
from backend.routing.policy_parsing import (
    RoutingPolicyValidationResult,
    load_routing_policy,
    validate_routing_policy,
)
from backend.routing.router import EmbeddingsRouterStage, LLMRouterStage, Router
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
    "SelectorPolicySpec",
    "TraceEvent",
    "default_routing_policy",
    "load_routing_policy",
    "validate_routing_policy",
]
