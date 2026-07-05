"""Tests for the E5-S1 Router pipeline executor.

Covers the story DoD: routing-accuracy (known inputs map to the expected
``task_type``/``path``), pipeline short-circuit by confidence across stages,
pluggability (a custom policy produces a different decision without touching
:mod:`backend.routing.router` or :mod:`backend.routing.service`), and the
``embeddings``/``llm-router`` stage stubs failing closed with a clear error
unless a caller injects a concrete implementation.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from backend.routing.contract import ROUTE_SCHEMA_VERSION, ContextDigest, ContextSignals, RouteInput, RouteRequest
from backend.routing.policy import (
    RouteConstraintsSpec,
    RouterDefaultSpec,
    RouterEmbeddingsStageSpec,
    RouterLLMStageSpec,
    RouterPipelineSpec,
    RouterRuleSpec,
    RouterRulesStageSpec,
    RoutingPolicy,
    default_routing_policy,
)
from backend.routing.router import Router, _StageResult
from backend.routing.service import RoutingService


def _req(text: str, *, has_tests: bool = False) -> RouteRequest:
    """Build a minimal RouteRequest around a free-text input."""
    return RouteRequest(
        schema_version=ROUTE_SCHEMA_VERSION,
        session_id="s1",
        run_id="r1",
        input=RouteInput(text=text),
        context_digest=ContextDigest(repo="acme/widgets", signals=ContextSignals(has_tests=has_tests)),
    )


def _policy(*stages: Any, default: RouterDefaultSpec | None = None) -> RoutingPolicy:
    """Build a minimal RoutingPolicy wrapping the given pipeline stages."""
    return RoutingPolicy(
        schema_version="1",
        id="autodev/routing-test",
        version="1.0.0",
        host_api=">=2.0 <3.0",
        router=RouterPipelineSpec(
            stages=tuple(stages),
            default=default
            or RouterDefaultSpec(
                task_type="unclassified", intent="unspecified", path=("navigator", "responder"), confidence=0.0
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Routing-accuracy: known inputs map to the expected task_type/path
# ---------------------------------------------------------------------------


def test_documentation_update_is_routed_by_text_pattern() -> None:
    """A README/doc-shaped request routes to the documentation-update path."""
    decision = Router().route(_req("please update the README and changelog"), default_routing_policy())
    assert decision.task_type == "documentation-update"
    assert decision.path == ("navigator", "analyzer", "responder")
    assert decision.confidence == 1.0


def test_validation_only_requires_both_has_tests_and_intent_hint() -> None:
    """The validation-only rule fires only when both signals are present."""
    policy = default_routing_policy()
    req = _req("run the checks", has_tests=True)

    decision = Router().route(req, policy, context={"intent": "validate"})
    assert decision.task_type == "validation-only"
    assert decision.path == ("navigator", "validator", "responder")

    # Missing the intent hint: falls through to the generic default.
    decision_no_hint = Router().route(req, policy)
    assert decision_no_hint.task_type == "existing-repo-change"


def test_devops_change_is_routed_by_intent_hint() -> None:
    """A devops intent hint routes to the devops-change path."""
    policy = default_routing_policy()
    decision = Router().route(_req("bump the deploy pipeline"), policy, context={"intent": "devops"})
    assert decision.task_type == "devops-change"
    assert decision.path == ("navigator", "analyzer", "devops", "responder")


def test_unmatched_input_falls_back_to_the_generic_default() -> None:
    """An input matching no rule falls back to the policy's default decision."""
    decision = Router().route(_req("implement a new caching layer"), default_routing_policy())
    assert decision.task_type == "existing-repo-change"
    assert decision.path == ("navigator", "analyzer", "architect", "coder", "devops", "validator", "responder")
    assert decision.confidence == 0.0


# ---------------------------------------------------------------------------
# Pipeline short-circuit by confidence
# ---------------------------------------------------------------------------


def test_low_confidence_match_cascades_to_the_next_stage() -> None:
    """A stage result below its confidence_floor cascades instead of winning."""
    low_confidence_stage = RouterRulesStageSpec(
        confidence_floor=0.9,
        rules=(RouterRuleSpec(when={"input.text": "hello"}, set={"task_type": "low", "path": ["a"]}, confidence=0.5),),
    )
    high_confidence_stage = RouterRulesStageSpec(
        confidence_floor=0.0,
        rules=(RouterRuleSpec(when={"input.text": "hello"}, set={"task_type": "high", "path": ["b"]}, confidence=1.0),),
    )
    policy = _policy(low_confidence_stage, high_confidence_stage)
    decision = Router().route(_req("hello"), policy)
    assert decision.task_type == "high"
    assert decision.confidence == 1.0


def test_sufficient_confidence_short_circuits_before_later_stages() -> None:
    """A stage result meeting its confidence_floor wins without reaching later stages."""
    winning_stage = RouterRulesStageSpec(
        confidence_floor=0.5,
        rules=(RouterRuleSpec(when={"input.text": "hello"}, set={"task_type": "first", "path": ["a"]}, confidence=0.8),),
    )
    unreachable_llm_stage = RouterLLMStageSpec(model="unused/model", max_cost_usd=0.0, only_if_confidence_below=1.0)
    policy = _policy(winning_stage, unreachable_llm_stage)
    # If the pipeline reached the llm-router stage it would raise NotImplementedError.
    decision = Router().route(_req("hello"), policy)
    assert decision.task_type == "first"


# ---------------------------------------------------------------------------
# Pluggability: a custom policy changes the decision without core changes
# ---------------------------------------------------------------------------


def test_custom_policy_produces_a_different_decision_without_core_changes() -> None:
    """A caller-supplied policy (no Router/RoutingService code change) reroutes."""
    custom_stage = RouterRulesStageSpec(
        confidence_floor=0.0,
        rules=(
            RouterRuleSpec(
                when={"input.text": "~=/(?i)security/"},
                set={"task_type": "security-review", "intent": "security", "path": ["navigator", "security-auditor", "responder"]},
            ),
        ),
    )
    custom_policy = _policy(
        custom_stage,
        default=RouterDefaultSpec(task_type="fallback", intent="unspecified", path=("navigator",), confidence=0.0),
    )
    decision = RoutingService(custom_policy).route(_req("please audit this for security issues"))
    assert decision.task_type == "security-review"
    assert decision.path == ("navigator", "security-auditor", "responder")

    # The built-in default policy classifies the very same input differently.
    default_decision = RoutingService(default_routing_policy()).route(_req("please audit this for security issues"))
    assert default_decision.task_type != "security-review"


def test_routing_service_forwards_context_to_a_fully_custom_router_plugin() -> None:
    """A RouterPlugin that is NOT a Router instance still receives `context` uniformly."""

    class _EchoContextRouter:
        """Minimal custom RouterPlugin that reports whatever context it received."""

        def route(
            self, req: RouteRequest, policy: RoutingPolicy, *, context: Mapping[str, Any] | None = None
        ) -> Any:
            """Return a RouteDecision whose task_type encodes the received context."""
            from backend.routing.contract import RouteConstraints, RouteDecision

            return RouteDecision(
                schema_version=ROUTE_SCHEMA_VERSION,
                task_type=f"context={dict(context or {})}",
                intent="unspecified",
                path=("navigator",),
                confidence=1.0,
                constraints=RouteConstraints(max_cost_usd=0.05, latency_class="interactive"),
                rationale="echoes context for the pluggability test",
            )

    service = RoutingService(default_routing_policy(), router=_EchoContextRouter())
    decision = service.route(_req("anything"), context={"intent": "devops"})
    assert decision.task_type == "context={'intent': 'devops'}"


def test_rule_can_override_default_constraints() -> None:
    """A rule's own ``set.constraints`` takes precedence over the policy default."""
    stage = RouterRulesStageSpec(
        confidence_floor=0.0,
        rules=(
            RouterRuleSpec(
                when={"input.text": "batch"},
                set={
                    "task_type": "batch-job",
                    "path": ["navigator"],
                    "constraints": {"max_cost_usd": 1.5, "latency_class": "batch"},
                },
            ),
        ),
    )
    policy = RoutingPolicy(
        schema_version="1",
        id="autodev/routing-test",
        version="1.0.0",
        host_api=">=2.0 <3.0",
        router=RouterPipelineSpec(
            stages=(stage,),
            default=RouterDefaultSpec(task_type="fallback", intent="unspecified", path=("navigator",)),
            constraints=RouteConstraintsSpec(max_cost_usd=0.05, latency_class="interactive"),
        ),
    )
    decision = Router().route(_req("batch"), policy)
    assert decision.constraints.max_cost_usd == 1.5
    assert decision.constraints.latency_class == "batch"


# ---------------------------------------------------------------------------
# Embeddings / LLM-router stage stubs
# ---------------------------------------------------------------------------


def test_embeddings_stage_raises_notimplementederror_when_reached() -> None:
    """The default embeddings stage handler fails closed with a clear message."""
    stage = RouterEmbeddingsStageSpec(dataset="autodev/intents@2026-06", threshold=0.72)
    policy = _policy(stage)
    with pytest.raises(NotImplementedError, match="embeddings"):
        Router().route(_req("anything"), policy)


def test_llm_router_stage_raises_notimplementederror_when_reached() -> None:
    """The default llm-router stage handler fails closed with a clear message."""
    stage = RouterLLMStageSpec(model="provider/router-small", max_cost_usd=0.01, only_if_confidence_below=0.9)
    policy = _policy(stage)
    with pytest.raises(NotImplementedError, match="llm-router"):
        Router().route(_req("anything"), policy)


def test_embeddings_stage_can_be_replaced_by_injection() -> None:
    """A caller-supplied EmbeddingsRouterStage bypasses the default stub."""

    class _AlwaysMatchEmbeddings:
        """Test double for EmbeddingsRouterStage that always reports a match."""

        def resolve(self, signals: Mapping[str, Any], spec: RouterEmbeddingsStageSpec) -> _StageResult:
            """Return a fixed, high-confidence stage result regardless of input."""
            return _StageResult(
                task_type="embedding-match",
                intent="unspecified",
                path=("navigator",),
                confidence=1.0,
                constraints=None,
                rationale="stub embeddings match",
            )

    stage = RouterEmbeddingsStageSpec(dataset="autodev/intents@2026-06", threshold=0.72)
    policy = _policy(stage)
    router = Router(embeddings_stage=_AlwaysMatchEmbeddings())
    decision = router.route(_req("anything"), policy)
    assert decision.task_type == "embedding-match"
