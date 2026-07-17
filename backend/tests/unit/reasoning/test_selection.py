"""Unit tests for backend/reasoning/selection.py (E4-S4).

Covers ``resolve_strategy``'s precedence chain (selector > flow_node >
manifest > policy_rule > default), the ``_matches``/``_match_value`` predicate
matcher, the ``_compare`` operator branches, and the ``_coerce`` helper's
numeric/ordinal-level/string fallback behavior.
"""

from __future__ import annotations

from backend.reasoning.policy import (
    ReasoningBudgetPolicy,
    ReasoningPolicy,
    SelectionRule,
    SelectionSpec,
)
from backend.reasoning.selection import resolve_strategy


def _policy(*rules: SelectionRule, default: str = "autodev/reasoning-default") -> ReasoningPolicy:
    """Build a minimal :class:`ReasoningPolicy` carrying only selection rules.

    Args:
        rules: Selection rules to install, evaluated in order.
        default: Strategy id used when no rule matches.

    Returns:
        A policy with a trivial budget, suitable for selection tests.
    """
    return ReasoningPolicy(
        schema_version="1",
        id="autodev/selection-test",
        version="1.0.0",
        host_api=">=2.0 <3.0",
        selection=SelectionSpec(default=default, rules=tuple(rules)),
        budget=ReasoningBudgetPolicy(tokens=1000, cost_usd=1.0, wall_clock_ms=1000, max_steps=1),
    )


def test_selector_choice_has_highest_precedence() -> None:
    """A dynamic Selector choice wins over every other precedence tier."""
    policy = _policy(SelectionRule(when={"complexity": "high"}, use="rule-strategy"))
    decision = resolve_strategy(
        policy,
        context={"complexity": "high"},
        manifest_strategy="manifest-strategy",
        node_override="node-strategy",
        selector_choice="selector-strategy",
    )
    assert decision.strategy_id == "selector-strategy"
    assert decision.source == "selector"
    assert decision.config == {}


def test_flow_node_override_wins_over_manifest_and_rules() -> None:
    """A Flow Node override wins when no Selector choice is present."""
    policy = _policy(SelectionRule(when={"complexity": "high"}, use="rule-strategy"))
    decision = resolve_strategy(
        policy,
        context={"complexity": "high"},
        manifest_strategy="manifest-strategy",
        node_override="node-strategy",
    )
    assert decision.strategy_id == "node-strategy"
    assert decision.source == "flow_node"


def test_manifest_strategy_wins_over_policy_rules() -> None:
    """An Agent Manifest declaration wins over policy rules when unopposed."""
    policy = _policy(SelectionRule(when={"complexity": "high"}, use="rule-strategy"))
    decision = resolve_strategy(
        policy,
        context={"complexity": "high"},
        manifest_strategy="manifest-strategy",
    )
    assert decision.strategy_id == "manifest-strategy"
    assert decision.source == "manifest"


def test_matching_policy_rule_wins_over_default_and_carries_config() -> None:
    """A matched policy rule is selected and its config is propagated."""
    policy = _policy(
        SelectionRule(when={"complexity": "high"}, use="rule-strategy", config={"max_depth": 3})
    )
    decision = resolve_strategy(policy, context={"complexity": "high"})
    assert decision.strategy_id == "rule-strategy"
    assert decision.source == "policy_rule"
    assert decision.config == {"max_depth": 3}


def test_no_matching_rule_falls_back_to_default() -> None:
    """When no rule matches and no override is given, the policy default is used."""
    policy = _policy(SelectionRule(when={"complexity": "high"}, use="rule-strategy"))
    decision = resolve_strategy(policy, context={"complexity": "low"})
    assert decision.strategy_id == "autodev/reasoning-default"
    assert decision.source == "default"


def test_no_context_falls_back_to_default() -> None:
    """Omitting context entirely (None) yields the default with no rule matching."""
    policy = _policy(SelectionRule(when={"complexity": "high"}, use="rule-strategy"))
    decision = resolve_strategy(policy, context=None)
    assert decision.strategy_id == "autodev/reasoning-default"
    assert decision.source == "default"


def test_first_matching_rule_wins_in_declaration_order() -> None:
    """Rules are evaluated first-match-wins in the order they were declared."""
    policy = _policy(
        SelectionRule(when={"complexity": "high"}, use="first-match"),
        SelectionRule(when={"complexity": "high"}, use="second-match"),
    )
    decision = resolve_strategy(policy, context={"complexity": "high"})
    assert decision.strategy_id == "first-match"


def test_missing_context_key_does_not_match() -> None:
    """A rule referencing a context key absent from the run context never matches."""
    policy = _policy(SelectionRule(when={"complexity": "high"}, use="rule-strategy"))
    decision = resolve_strategy(policy, context={"other_key": "value"})
    assert decision.source == "default"


def test_ordinal_level_comparison_operators() -> None:
    """The ``>=``, ``<=``, ``>``, ``<`` operators compare ordinal levels correctly."""
    policy = _policy(SelectionRule(when={"complexity": ">=high"}, use="matched"))
    assert resolve_strategy(policy, context={"complexity": "high"}).strategy_id == "matched"
    assert resolve_strategy(policy, context={"complexity": "critical"}).strategy_id == "matched"
    assert resolve_strategy(policy, context={"complexity": "medium"}).source == "default"

    policy_lte = _policy(SelectionRule(when={"complexity": "<=medium"}, use="matched"))
    assert resolve_strategy(policy_lte, context={"complexity": "low"}).strategy_id == "matched"
    assert resolve_strategy(policy_lte, context={"complexity": "high"}).source == "default"

    policy_gt = _policy(SelectionRule(when={"complexity": ">medium"}, use="matched"))
    assert resolve_strategy(policy_gt, context={"complexity": "high"}).strategy_id == "matched"
    assert resolve_strategy(policy_gt, context={"complexity": "medium"}).source == "default"

    policy_lt = _policy(SelectionRule(when={"complexity": "<medium"}, use="matched"))
    assert resolve_strategy(policy_lt, context={"complexity": "low"}).strategy_id == "matched"
    assert resolve_strategy(policy_lt, context={"complexity": "medium"}).source == "default"


def test_numeric_comparison_operator() -> None:
    """The ``>=`` operator compares numeric context values against a numeric threshold."""
    policy = _policy(SelectionRule(when={"budget.tokens": ">=20000"}, use="matched"))
    assert resolve_strategy(policy, context={"budget.tokens": 25000}).strategy_id == "matched"
    assert resolve_strategy(policy, context={"budget.tokens": 5000}).source == "default"


def test_equality_operator_explicit() -> None:
    """The explicit ``==`` operator matches when the coerced values are equal."""
    policy = _policy(SelectionRule(when={"complexity": "==high"}, use="matched"))
    assert resolve_strategy(policy, context={"complexity": "high"}).strategy_id == "matched"
    assert resolve_strategy(policy, context={"complexity": "low"}).source == "default"


def test_plain_string_predicate_is_exact_match_case_insensitive() -> None:
    """A predicate with no operator prefix falls back to case-insensitive exact match."""
    policy = _policy(SelectionRule(when={"language": "Python"}, use="matched"))
    assert resolve_strategy(policy, context={"language": "python"}).strategy_id == "matched"
    assert resolve_strategy(policy, context={"language": "rust"}).source == "default"


def test_non_string_expected_value_uses_direct_equality() -> None:
    """A non-string expected value (e.g. int) is compared with direct equality."""
    policy = _policy(SelectionRule(when={"retry_count": 3}, use="matched"))
    assert resolve_strategy(policy, context={"retry_count": 3}).strategy_id == "matched"
    assert resolve_strategy(policy, context={"retry_count": 4}).source == "default"


def test_type_mismatch_between_operands_returns_false() -> None:
    """Comparing a numeric actual value against a non-numeric, non-level expected value fails."""
    policy = _policy(SelectionRule(when={"complexity": ">=unknown_level"}, use="matched"))
    decision = resolve_strategy(policy, context={"complexity": 42})
    assert decision.source == "default"


def test_all_predicates_in_rule_must_match() -> None:
    """A multi-key ``when`` clause only matches when every predicate holds."""
    policy = _policy(
        SelectionRule(when={"complexity": "high", "language": "python"}, use="matched")
    )
    assert (
        resolve_strategy(policy, context={"complexity": "high", "language": "python"}).strategy_id
        == "matched"
    )
    assert resolve_strategy(policy, context={"complexity": "high", "language": "rust"}).source == "default"
