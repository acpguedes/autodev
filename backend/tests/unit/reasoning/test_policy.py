"""Unit tests for backend/reasoning/policy.py (E4-S1).

Covers ``validate_reasoning_policy`` (required keys, id/version/hostApi
format checks, and the selection/budget/guardrails/tracing sub-parsers),
``load_reasoning_policy`` (disk I/O and error propagation), the E4-S1
``select_strategy`` stub, and the ``default_reasoning_policy`` factory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.reasoning.policy import (
    GuardrailSpec,
    ReasoningPolicy,
    default_reasoning_policy,
    load_reasoning_policy,
    select_strategy,
    validate_reasoning_policy,
)


def _minimal_raw(**overrides: Any) -> dict[str, Any]:
    """Build a minimal valid raw reasoning-policy document, with overrides applied.

    Args:
        overrides: Top-level keys to override or add.

    Returns:
        A dict with all required top-level fields, merged with ``overrides``.
    """
    raw: dict[str, Any] = {
        "schemaVersion": "1",
        "id": "autodev/reasoning-policy-test",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "selection": {"default": "autodev/reasoning-react"},
        "budget": {"tokens": 1000, "cost_usd": 0.5, "wall_clock_ms": 5000, "max_steps": 5},
    }
    raw.update(overrides)
    return raw


# --- Top-level structure -----------------------------------------------------


def test_missing_required_top_level_keys_are_all_reported() -> None:
    """Every missing required top-level key produces its own error entry."""
    result = validate_reasoning_policy({})
    assert result.valid is False
    for key in ("schemaVersion", "id", "version", "hostApi", "selection", "budget"):
        assert f"{key} is required" in result.errors


def test_minimal_valid_document_parses_successfully() -> None:
    """A minimal valid document parses into a ReasoningPolicy with no errors."""
    result = validate_reasoning_policy(_minimal_raw())
    assert result.valid is True
    assert result.errors == []
    assert result.policy is not None
    assert result.policy.id == "autodev/reasoning-policy-test"
    assert result.policy.selection.default == "autodev/reasoning-react"
    assert result.policy.budget.tokens == 1000


def test_invalid_id_format_rejected() -> None:
    """An id not matching namespace/name kebab-case format is rejected."""
    result = validate_reasoning_policy(_minimal_raw(id="Not Valid ID"))
    assert result.valid is False
    assert "id must use namespace/name kebab-case format" in result.errors


def test_invalid_version_format_rejected() -> None:
    """A non-SemVer version string is rejected."""
    result = validate_reasoning_policy(_minimal_raw(version="v1"))
    assert result.valid is False
    assert "version must be SemVer MAJOR.MINOR.PATCH" in result.errors


def test_invalid_host_api_range_rejected() -> None:
    """A syntactically invalid hostApi expression is rejected."""
    result = validate_reasoning_policy(_minimal_raw(hostApi="not a range!!"))
    assert result.valid is False
    assert "hostApi must be a supported range expression" in result.errors


def test_host_api_wildcard_is_accepted() -> None:
    """The '*' wildcard is a valid hostApi range."""
    result = validate_reasoning_policy(_minimal_raw(hostApi="*"))
    assert result.valid is True
    assert result.policy is not None
    assert result.policy.host_api == "*"


# --- selection ----------------------------------------------------------------


def test_selection_not_object_rejected() -> None:
    """A non-dict selection value is rejected and yields an empty default."""
    result = validate_reasoning_policy(_minimal_raw(selection="oops"))
    assert "selection must be an object" in result.errors


def test_selection_missing_default_is_required() -> None:
    """Omitting selection.default is rejected."""
    result = validate_reasoning_policy(_minimal_raw(selection={}))
    assert "selection.default is required" in result.errors


def test_selection_rules_not_list_rejected() -> None:
    """A non-list selection.rules value is rejected and treated as empty."""
    result = validate_reasoning_policy(
        _minimal_raw(selection={"default": "autodev/reasoning-react", "rules": "oops"})
    )
    assert "selection.rules must be a list" in result.errors


def test_selection_rule_not_object_rejected() -> None:
    """A rules[] entry that is not a dict is rejected."""
    result = validate_reasoning_policy(
        _minimal_raw(selection={"default": "autodev/reasoning-react", "rules": ["oops"]})
    )
    assert "selection.rules[0] must be an object" in result.errors


def test_selection_rule_missing_when_rejected() -> None:
    """A rule with a missing or empty 'when' predicate is rejected."""
    result = validate_reasoning_policy(
        _minimal_raw(
            selection={
                "default": "autodev/reasoning-react",
                "rules": [{"when": {}, "use": "x"}],
            }
        )
    )
    assert "selection.rules[0].when must be a non-empty object" in result.errors


def test_selection_rule_missing_use_rejected() -> None:
    """A rule missing 'use' is rejected."""
    result = validate_reasoning_policy(
        _minimal_raw(
            selection={
                "default": "autodev/reasoning-react",
                "rules": [{"when": {"complexity": "high"}}],
            }
        )
    )
    assert "selection.rules[0].use is required" in result.errors


def test_selection_rule_config_not_object_defaults_to_empty() -> None:
    """A rule whose config is not a dict is rejected and defaults to an empty config."""
    result = validate_reasoning_policy(
        _minimal_raw(
            selection={
                "default": "autodev/reasoning-react",
                "rules": [{"when": {"complexity": "high"}, "use": "x", "config": "oops"}],
            }
        )
    )
    assert "selection.rules[0].config must be an object" in result.errors


def test_selection_rule_valid_full_spec() -> None:
    """A fully specified valid rule parses into a SelectionRule with its config."""
    result = validate_reasoning_policy(
        _minimal_raw(
            selection={
                "default": "autodev/reasoning-react",
                "rules": [
                    {"when": {"complexity": "high"}, "use": "autodev/reasoning-tot", "config": {"depth": 3}}
                ],
            }
        )
    )
    assert result.valid is True
    assert result.policy is not None
    rule = result.policy.selection.rules[0]
    assert rule.when == {"complexity": "high"}
    assert rule.use == "autodev/reasoning-tot"
    assert rule.config == {"depth": 3}


# --- budget ---------------------------------------------------------------


def test_budget_not_object_rejected_yields_zeroed_defaults() -> None:
    """A non-dict budget value is rejected and yields a zeroed budget."""
    result = validate_reasoning_policy(_minimal_raw(budget="oops"))
    assert "budget must be an object" in result.errors


def test_budget_non_positive_tokens_rejected() -> None:
    """A zero or negative budget.tokens value is rejected."""
    result = validate_reasoning_policy(
        _minimal_raw(budget={"tokens": 0, "cost_usd": 0.5, "wall_clock_ms": 1000, "max_steps": 1})
    )
    assert "budget.tokens must be a positive integer" in result.errors


def test_budget_bool_tokens_rejected() -> None:
    """A boolean budget.tokens value is rejected (bool is an int subclass)."""
    result = validate_reasoning_policy(
        _minimal_raw(budget={"tokens": True, "cost_usd": 0.5, "wall_clock_ms": 1000, "max_steps": 1})
    )
    assert "budget.tokens must be a positive integer" in result.errors


def test_budget_non_positive_cost_usd_rejected() -> None:
    """A zero or negative budget.cost_usd value is rejected."""
    result = validate_reasoning_policy(
        _minimal_raw(budget={"tokens": 100, "cost_usd": -1.0, "wall_clock_ms": 1000, "max_steps": 1})
    )
    assert "budget.cost_usd must be a positive number" in result.errors


def test_budget_bool_cost_usd_rejected() -> None:
    """A boolean budget.cost_usd value is rejected (bool is an int subclass)."""
    result = validate_reasoning_policy(
        _minimal_raw(budget={"tokens": 100, "cost_usd": True, "wall_clock_ms": 1000, "max_steps": 1})
    )
    assert "budget.cost_usd must be a positive number" in result.errors


def test_budget_on_exceed_defaults_to_fail_closed() -> None:
    """Omitting budget.on_exceed defaults to 'fail_closed'."""
    result = validate_reasoning_policy(
        _minimal_raw(budget={"tokens": 100, "cost_usd": 0.5, "wall_clock_ms": 1000, "max_steps": 1})
    )
    assert result.valid is True
    assert result.policy is not None
    assert result.policy.budget.on_exceed == "fail_closed"


def test_budget_on_exceed_degrade_to_is_valid() -> None:
    """A 'degrade_to:<strategy-id>' on_exceed value is accepted."""
    result = validate_reasoning_policy(
        _minimal_raw(
            budget={
                "tokens": 100,
                "cost_usd": 0.5,
                "wall_clock_ms": 1000,
                "max_steps": 1,
                "on_exceed": "degrade_to:autodev/reasoning-react",
            }
        )
    )
    assert result.valid is True
    assert result.policy is not None
    assert result.policy.budget.on_exceed == "degrade_to:autodev/reasoning-react"


def test_budget_on_exceed_invalid_value_rejected() -> None:
    """An on_exceed value that is neither fail_closed nor degrade_to:* is rejected."""
    result = validate_reasoning_policy(
        _minimal_raw(
            budget={
                "tokens": 100,
                "cost_usd": 0.5,
                "wall_clock_ms": 1000,
                "max_steps": 1,
                "on_exceed": "ignore",
            }
        )
    )
    assert any("budget.on_exceed must be" in e for e in result.errors)


# --- guardrails -------------------------------------------------------------


def test_guardrails_absent_defaults_to_empty() -> None:
    """Omitting guardrails entirely yields an empty tuple with no error."""
    result = validate_reasoning_policy(_minimal_raw())
    assert result.valid is True
    assert result.policy is not None
    assert result.policy.guardrails == ()


def test_guardrails_not_list_rejected() -> None:
    """A non-list guardrails value is rejected."""
    result = validate_reasoning_policy(_minimal_raw(guardrails="oops"))
    assert "guardrails must be a list" in result.errors


def test_guardrails_item_not_object_rejected() -> None:
    """A guardrails[] entry that is not a dict is rejected."""
    result = validate_reasoning_policy(_minimal_raw(guardrails=["oops"]))
    assert "guardrails[0] must be an object" in result.errors


def test_guardrails_missing_id_rejected() -> None:
    """A guardrail entry missing 'id' is rejected."""
    result = validate_reasoning_policy(_minimal_raw(guardrails=[{"on_violation": "block"}]))
    assert "guardrails[0].id is required" in result.errors


def test_guardrails_invalid_on_violation_rejected() -> None:
    """A guardrail entry with an unrecognized on_violation value is rejected."""
    result = validate_reasoning_policy(
        _minimal_raw(guardrails=[{"id": "schema_conformance", "on_violation": "ignore"}])
    )
    assert any("on_violation must be one of" in e for e in result.errors)


def test_guardrails_valid_entries_parsed_in_order() -> None:
    """Valid guardrail entries are parsed and preserved in document order."""
    result = validate_reasoning_policy(
        _minimal_raw(
            guardrails=[
                {"id": "schema_conformance", "on_violation": "block"},
                {"id": "toxicity", "on_violation": "warn"},
            ]
        )
    )
    assert result.valid is True
    assert result.policy is not None
    assert result.policy.guardrails == (
        GuardrailSpec(id="schema_conformance", on_violation="block"),
        GuardrailSpec(id="toxicity", on_violation="warn"),
    )


# --- tracing ------------------------------------------------------------------


def test_tracing_absent_uses_defaults() -> None:
    """Omitting tracing entirely yields the default TracingSpec."""
    result = validate_reasoning_policy(_minimal_raw())
    assert result.valid is True
    assert result.policy is not None
    assert result.policy.tracing.level == "full"
    assert result.policy.tracing.record_prompts is True
    assert result.policy.tracing.deterministic_replay is True


def test_tracing_empty_dict_uses_defaults() -> None:
    """An explicit empty tracing dict also yields the default TracingSpec."""
    result = validate_reasoning_policy(_minimal_raw(tracing={}))
    assert result.valid is True
    assert result.policy is not None
    assert result.policy.tracing.level == "full"


def test_tracing_not_object_rejected() -> None:
    """A non-dict, non-empty tracing value is rejected and defaults are used."""
    result = validate_reasoning_policy(_minimal_raw(tracing="oops"))
    assert "tracing must be an object" in result.errors


def test_tracing_invalid_level_rejected() -> None:
    """An unrecognized tracing.level value is rejected."""
    result = validate_reasoning_policy(_minimal_raw(tracing={"level": "verbose"}))
    assert any("tracing.level must be one of" in e for e in result.errors)


def test_tracing_invalid_record_prompts_type_rejected() -> None:
    """A non-bool tracing.record_prompts value is rejected."""
    result = validate_reasoning_policy(_minimal_raw(tracing={"record_prompts": "yes"}))
    assert "tracing.record_prompts must be a boolean" in result.errors


def test_tracing_invalid_deterministic_replay_type_rejected() -> None:
    """A non-bool tracing.deterministic_replay value is rejected."""
    result = validate_reasoning_policy(_minimal_raw(tracing={"deterministic_replay": "yes"}))
    assert "tracing.deterministic_replay must be a boolean" in result.errors


def test_tracing_valid_full_spec() -> None:
    """A fully specified valid tracing section parses without error."""
    result = validate_reasoning_policy(
        _minimal_raw(tracing={"level": "summary", "record_prompts": False, "deterministic_replay": False})
    )
    assert result.valid is True
    assert result.policy is not None
    assert result.policy.tracing.level == "summary"
    assert result.policy.tracing.record_prompts is False
    assert result.policy.tracing.deterministic_replay is False


# --- load_reasoning_policy ------------------------------------------------


def test_load_reasoning_policy_success(tmp_path: Path) -> None:
    """A well-formed YAML document on disk loads into a validated ReasoningPolicy."""
    policy_path = tmp_path / "reasoning-policy.yaml"
    policy_path.write_text(yaml.safe_dump(_minimal_raw()), encoding="utf-8")
    policy = load_reasoning_policy(policy_path)
    assert policy.id == "autodev/reasoning-policy-test"


def test_load_reasoning_policy_rejects_non_mapping_document(tmp_path: Path) -> None:
    """A YAML document whose root is not a mapping raises ValueError."""
    policy_path = tmp_path / "reasoning-policy.yaml"
    policy_path.write_text(yaml.safe_dump(["a", "list", "not", "a", "map"]), encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a mapping"):
        load_reasoning_policy(policy_path)


def test_load_reasoning_policy_propagates_validation_errors(tmp_path: Path) -> None:
    """A YAML document that fails validation raises ValueError with joined errors."""
    policy_path = tmp_path / "reasoning-policy.yaml"
    policy_path.write_text(yaml.safe_dump({}), encoding="utf-8")
    with pytest.raises(ValueError, match="schemaVersion is required"):
        load_reasoning_policy(policy_path)


# --- select_strategy (E4-S1 stub) ------------------------------------------


def _policy_with_rule(when: dict[str, Any], use: str, default: str = "autodev/reasoning-default") -> ReasoningPolicy:
    """Build a ReasoningPolicy with a single exact-match selection rule.

    Args:
        when: Exact-match predicate for the rule.
        use: Strategy id to select when ``when`` matches.
        default: Strategy id used when no rule matches.

    Returns:
        A policy suitable for exercising ``select_strategy``.
    """
    result = validate_reasoning_policy(
        _minimal_raw(selection={"default": default, "rules": [{"when": when, "use": use}]})
    )
    assert result.policy is not None
    return result.policy


def test_select_strategy_exact_match_selects_rule() -> None:
    """select_strategy picks a rule when every 'when' key matches exactly."""
    policy = _policy_with_rule({"complexity": "high"}, use="autodev/reasoning-tot")
    assert select_strategy(policy, {"complexity": "high"}) == "autodev/reasoning-tot"


def test_select_strategy_partial_match_falls_back_to_default() -> None:
    """select_strategy requires every 'when' key to match exactly (no operators)."""
    policy = _policy_with_rule({"complexity": "high", "language": "python"}, use="autodev/reasoning-tot")
    assert select_strategy(policy, {"complexity": "high", "language": "rust"}) == "autodev/reasoning-default"


def test_select_strategy_no_context_returns_default() -> None:
    """select_strategy returns the policy default when context is omitted or empty."""
    policy = _policy_with_rule({"complexity": "high"}, use="autodev/reasoning-tot")
    assert select_strategy(policy) == "autodev/reasoning-default"
    assert select_strategy(policy, {}) == "autodev/reasoning-default"


def test_select_strategy_does_not_support_operator_expressions() -> None:
    """select_strategy is exact-match only: an operator-prefixed value never matches."""
    policy = _policy_with_rule({"complexity": ">=high"}, use="autodev/reasoning-tot")
    # The literal string ">=high" never equals any realistic context value.
    assert select_strategy(policy, {"complexity": ">=high"}) == "autodev/reasoning-tot"
    assert select_strategy(policy, {"complexity": "critical"}) == "autodev/reasoning-default"


# --- default_reasoning_policy factory ---------------------------------------


def test_default_reasoning_policy_uses_documented_defaults() -> None:
    """default_reasoning_policy() with no overrides builds the reference §8.4 defaults."""
    policy = default_reasoning_policy()
    assert policy.selection.default == "autodev/reasoning-react"
    assert policy.budget.tokens == 24000
    assert policy.budget.cost_usd == 0.75
    assert policy.budget.wall_clock_ms == 45000
    assert policy.budget.max_steps == 12
    assert policy.budget.on_exceed == "fail_closed"
    assert policy.guardrails == ()
    assert policy.tracing == policy.tracing.__class__()


def test_default_reasoning_policy_honors_overrides() -> None:
    """default_reasoning_policy() applies caller-supplied overrides."""
    policy = default_reasoning_policy(
        default_strategy="autodev/reasoning-tot",
        tokens=5000,
        cost_usd=0.1,
        wall_clock_ms=1000,
        max_steps=3,
        on_exceed="degrade_to:autodev/reasoning-react",
        guardrails=(GuardrailSpec(id="toxicity", on_violation="warn"),),
    )
    assert policy.selection.default == "autodev/reasoning-tot"
    assert policy.budget.tokens == 5000
    assert policy.budget.on_exceed == "degrade_to:autodev/reasoning-react"
    assert policy.guardrails == (GuardrailSpec(id="toxicity", on_violation="warn"),)
