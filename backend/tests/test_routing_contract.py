"""Contract tests for the E5-S1 Router contract and routing policy model.

Covers the story DoD: a ``routing-policy.yaml`` document (reference §9.3)
parses into a typed :class:`RoutingPolicy`, invalid documents are rejected
with actionable errors, and a conforming :class:`RouterPlugin` implementation
(:class:`Router`) classifies a :class:`RouteRequest` into a typed
:class:`RouteDecision` end-to-end through :class:`RoutingService`, with the
decision recorded to the trace sink.
"""

from __future__ import annotations

from typing import Any

from backend.routing.contract import (
    ROUTE_SCHEMA_VERSION,
    ROUTING_CONTRACT_HOST_API,
    ContextDigest,
    ContextSignals,
    RouteInput,
    RouteRequest,
    TraceEvent,
)
from backend.routing.policy import (
    RouterEmbeddingsStageSpec,
    RouterLLMStageSpec,
    RouterRulesStageSpec,
    RoutingPolicy,
    default_routing_policy,
)
from backend.routing.policy_parsing import validate_routing_policy
from backend.routing.router import Router
from backend.routing.service import RoutingService


def _raw_policy_document() -> dict[str, Any]:
    """Build a raw ``routing-policy.yaml``-shaped document for validation tests."""
    return {
        "schemaVersion": "1.0",
        "id": "autodev/routing-test",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "router": {
            "pipeline": [
                {
                    "kind": "rules",
                    "confidence_floor": 0.0,
                    "rules": [
                        {
                            "when": {"input.text": r"~=/(?i)\b(doc|readme)\b/"},
                            "set": {
                                "task_type": "documentation-update",
                                "intent": "docs",
                                "path": ["navigator", "responder"],
                            },
                        }
                    ],
                },
                {"kind": "embeddings", "dataset": "autodev/intents@2026-06", "threshold": 0.72},
                {"kind": "llm-router", "model": "provider/router-small", "max_cost_usd": 0.01, "only_if_confidence_below": 0.72},
            ],
            "default": {
                "task_type": "existing-repo-change",
                "intent": "unspecified",
                "path": ["navigator", "coder", "responder"],
            },
        },
        "selector": {"pipeline": []},
        "guardrails": {"input": ["pii-filter"], "output": ["schema-validate"]},
        "fallback": {"default": "fail_closed"},
    }


def test_validate_routing_policy_accepts_a_full_pipeline_document() -> None:
    """A well-formed policy document parses into a typed RoutingPolicy."""
    result = validate_routing_policy(_raw_policy_document())
    assert result.valid, result.errors
    policy = result.policy
    assert policy is not None
    assert policy.id == "autodev/routing-test"
    assert len(policy.router.stages) == 3
    assert isinstance(policy.router.stages[0], RouterRulesStageSpec)
    assert isinstance(policy.router.stages[1], RouterEmbeddingsStageSpec)
    assert isinstance(policy.router.stages[2], RouterLLMStageSpec)
    assert policy.router.default.task_type == "existing-repo-change"
    # E5-S2 placeholders are parsed but not structurally validated this story.
    assert policy.selector.raw == {"pipeline": []}
    assert policy.guardrails.raw["input"] == ["pii-filter"]
    assert policy.fallback.raw["default"] == "fail_closed"


def test_validate_routing_policy_rejects_missing_required_fields() -> None:
    """Missing top-level required fields are reported, not silently defaulted."""
    raw = _raw_policy_document()
    del raw["router"]
    del raw["id"]
    result = validate_routing_policy(raw)
    assert not result.valid
    assert result.policy is None
    assert any("router is required" in error for error in result.errors)
    assert any("id is required" in error for error in result.errors)


def test_validate_routing_policy_rejects_bad_semver_and_rule_shape() -> None:
    """Invalid version strings and malformed rules are both caught."""
    raw = _raw_policy_document()
    raw["version"] = "not-a-version"
    raw["router"]["pipeline"][0]["rules"][0]["set"] = {"task_type": "x"}  # missing "path"
    result = validate_routing_policy(raw)
    assert not result.valid
    assert any("version must be SemVer" in error for error in result.errors)
    assert any("set must be an object with task_type and path" in error for error in result.errors)


def test_validate_routing_policy_rejects_a_non_string_path_entry() -> None:
    """A rule's set.path must be a list of strings, not a bare string or mixed list."""
    raw = _raw_policy_document()
    raw["router"]["pipeline"][0]["rules"][0]["set"]["path"] = "responder"
    result = validate_routing_policy(raw)
    assert not result.valid
    assert any("set.path must be a list of strings" in error for error in result.errors)


def test_validate_routing_policy_rejects_an_invalid_regex_pattern() -> None:
    """A malformed '~=' regex in a rule's when-predicate is caught at parse time."""
    raw = _raw_policy_document()
    raw["router"]["pipeline"][0]["rules"][0]["when"] = {"input.text": "~=/(unclosed(group/"}
    result = validate_routing_policy(raw)
    assert not result.valid
    assert any("invalid regex pattern" in error for error in result.errors)


def test_validate_routing_policy_rejects_malformed_rule_constraints() -> None:
    """A rule's optional set.constraints is validated with the same rigor as router.constraints."""
    raw = _raw_policy_document()
    raw["router"]["pipeline"][0]["rules"][0]["set"]["constraints"] = {"max_cost_usd": "not-a-number"}
    result = validate_routing_policy(raw)
    assert not result.valid
    assert any("must be a non-negative number" in error for error in result.errors)


def test_validate_routing_policy_rejects_non_string_version_field() -> None:
    """An unquoted YAML number for `version` is a type error, not silently emptied."""
    raw = _raw_policy_document()
    raw["version"] = 1.0  # yaml.safe_load would parse an unquoted `1.0` as a float
    result = validate_routing_policy(raw)
    assert not result.valid
    assert any("version must be a string" in error for error in result.errors)


def test_default_routing_policy_is_valid_and_pluggable_by_construction() -> None:
    """The built-in default policy is a normal, valid RoutingPolicy instance."""
    policy = default_routing_policy()
    assert isinstance(policy, RoutingPolicy)
    assert policy.host_api == ROUTING_CONTRACT_HOST_API
    assert len(policy.router.stages) == 1
    assert isinstance(policy.router.stages[0], RouterRulesStageSpec)


def test_router_conforms_to_the_contract_end_to_end() -> None:
    """A conforming RouterPlugin classifies a RouteRequest into a RouteDecision."""
    router = Router()
    policy = default_routing_policy()
    req = RouteRequest(
        schema_version=ROUTE_SCHEMA_VERSION,
        session_id="s1",
        run_id="r1",
        input=RouteInput(text="update the README with new install steps"),
        context_digest=ContextDigest(repo="acme/widgets", signals=ContextSignals(has_tests=True)),
    )
    decision = router.route(req, policy)
    assert decision.schema_version == ROUTE_SCHEMA_VERSION
    assert decision.task_type == "documentation-update"
    assert decision.path == ("navigator", "analyzer", "responder")
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.rationale  # human-readable justification is never empty
    assert decision.constraints.latency_class in {"interactive", "batch"}


def test_routing_service_records_a_decision_trace_event() -> None:
    """Every RouteDecision produced by the service is recorded to the trace sink."""
    events: list[TraceEvent] = []
    service = RoutingService(default_routing_policy(), on_event=events.append)
    req = RouteRequest(
        schema_version=ROUTE_SCHEMA_VERSION,
        session_id="s1",
        run_id="r1",
        input=RouteInput(text="please refactor the payments module"),
    )
    decision = service.route(req)
    assert len(events) == 1
    event = events[0]
    assert event.name == "router.decision.recorded"
    assert event.payload["task_type"] == decision.task_type
    assert event.payload["path"] == list(decision.path)
    assert event.payload["session_id"] == "s1"
    assert event.payload["run_id"] == "r1"
