"""Unit tests for backend/routing/selector_policy_parsing.py (E5-S2).

Covers ``parse_selector_section`` and its per-stage-kind helpers: the
absent/None section, non-object section, non-list pipeline, each of the
three stage kinds (capability-matching, cost-aware, score-weighted) in both
valid and invalid forms, unknown stage kinds, and the tie_breaker validation
branch.
"""

from __future__ import annotations

from backend.routing.policy import (
    SelectorCapabilityMatchingStageSpec,
    SelectorCostAwareStageSpec,
    SelectorScoreWeightedStageSpec,
)
from backend.routing.selector_policy_parsing import parse_selector_section


def test_absent_selector_section_returns_empty_pipeline() -> None:
    """A None raw value parses to an empty SelectorPolicySpec with no errors."""
    errors: list[str] = []
    spec = parse_selector_section(None, errors)
    assert errors == []
    assert spec.pipeline.stages == ()
    assert spec.pipeline.tie_breaker == "lowest_cost"


def test_non_object_selector_section_records_error() -> None:
    """A non-dict raw value is rejected with a top-level type error."""
    errors: list[str] = []
    spec = parse_selector_section(["not", "a", "dict"], errors)
    assert errors == ["selector must be an object"]
    assert spec.raw == {}


def test_non_list_pipeline_records_error_and_defaults_to_empty() -> None:
    """A non-list pipeline value is rejected and treated as an empty pipeline."""
    errors: list[str] = []
    spec = parse_selector_section({"pipeline": "oops"}, errors)
    assert "selector.pipeline must be a list" in errors
    assert spec.pipeline.stages == ()


def test_invalid_tie_breaker_records_error_and_defaults() -> None:
    """An invalid tie_breaker value is rejected and reset to the default."""
    errors: list[str] = []
    spec = parse_selector_section({"tie_breaker": "coin_flip"}, errors)
    assert any("tie_breaker must be one of" in e for e in errors)
    assert spec.pipeline.tie_breaker == "lowest_cost"


def test_valid_tie_breaker_is_preserved() -> None:
    """A valid tie_breaker value passes through unchanged with no error."""
    errors: list[str] = []
    spec = parse_selector_section({"tie_breaker": "lowest_cost"}, errors)
    assert errors == []
    assert spec.pipeline.tie_breaker == "lowest_cost"


def test_stage_entry_not_an_object_is_rejected() -> None:
    """A pipeline entry that is not a dict is skipped, with an error recorded."""
    errors: list[str] = []
    spec = parse_selector_section({"pipeline": ["not-a-dict"]}, errors)
    assert errors == ["selector.pipeline[0] must be an object"]
    assert spec.pipeline.stages == ()


def test_stage_entry_unknown_kind_is_rejected() -> None:
    """An unrecognized stage kind is rejected with the valid-kinds list."""
    errors: list[str] = []
    spec = parse_selector_section({"pipeline": [{"kind": "bogus"}]}, errors)
    assert len(errors) == 1
    assert "pipeline[0].kind must be one of" in errors[0]
    assert spec.pipeline.stages == ()


def test_capability_matching_stage_defaults_require_all_true() -> None:
    """capability-matching with no require_all defaults to True."""
    errors: list[str] = []
    spec = parse_selector_section(
        {"pipeline": [{"kind": "capability-matching"}]}, errors
    )
    assert errors == []
    assert len(spec.pipeline.stages) == 1
    stage = spec.pipeline.stages[0]
    assert isinstance(stage, SelectorCapabilityMatchingStageSpec)
    assert stage.require_all is True


def test_capability_matching_stage_invalid_require_all_type() -> None:
    """A non-bool require_all is rejected and reset to True."""
    errors: list[str] = []
    spec = parse_selector_section(
        {"pipeline": [{"kind": "capability-matching", "require_all": "yes"}]},
        errors,
    )
    assert any("require_all must be a boolean" in e for e in errors)
    stage = spec.pipeline.stages[0]
    assert isinstance(stage, SelectorCapabilityMatchingStageSpec)
    assert stage.require_all is True


def test_capability_matching_stage_explicit_false() -> None:
    """An explicit require_all=False is honored."""
    errors: list[str] = []
    spec = parse_selector_section(
        {"pipeline": [{"kind": "capability-matching", "require_all": False}]},
        errors,
    )
    assert errors == []
    stage = spec.pipeline.stages[0]
    assert isinstance(stage, SelectorCapabilityMatchingStageSpec)
    assert stage.require_all is False


def test_cost_aware_stage_defaults() -> None:
    """cost-aware with no fields defaults to minimize_cost and respect=True/True."""
    errors: list[str] = []
    spec = parse_selector_section({"pipeline": [{"kind": "cost-aware"}]}, errors)
    assert errors == []
    stage = spec.pipeline.stages[0]
    assert isinstance(stage, SelectorCostAwareStageSpec)
    assert stage.objective == "minimize_cost"
    assert stage.respect_run_budget is True
    assert stage.respect_tenant_quota is True


def test_cost_aware_stage_invalid_objective_defaults() -> None:
    """An invalid objective value is rejected and reset to minimize_cost."""
    errors: list[str] = []
    spec = parse_selector_section(
        {"pipeline": [{"kind": "cost-aware", "objective": "maximize_fun"}]}, errors
    )
    assert any("objective must be one of" in e for e in errors)
    stage = spec.pipeline.stages[0]
    assert isinstance(stage, SelectorCostAwareStageSpec)
    assert stage.objective == "minimize_cost"


def test_cost_aware_stage_non_dict_respect_defaults() -> None:
    """A non-dict respect value is rejected and both flags default to True."""
    errors: list[str] = []
    spec = parse_selector_section(
        {"pipeline": [{"kind": "cost-aware", "respect": "nope"}]}, errors
    )
    assert any("respect must be an object" in e for e in errors)
    stage = spec.pipeline.stages[0]
    assert isinstance(stage, SelectorCostAwareStageSpec)
    assert stage.respect_run_budget is True
    assert stage.respect_tenant_quota is True


def test_cost_aware_stage_invalid_respect_flags() -> None:
    """Non-bool respect.run_budget/tenant_quota are rejected and reset to True."""
    errors: list[str] = []
    spec = parse_selector_section(
        {
            "pipeline": [
                {
                    "kind": "cost-aware",
                    "respect": {"run_budget": "yes", "tenant_quota": 1},
                }
            ]
        },
        errors,
    )
    assert any("respect.run_budget must be a boolean" in e for e in errors)
    assert any("respect.tenant_quota must be a boolean" in e for e in errors)
    stage = spec.pipeline.stages[0]
    assert isinstance(stage, SelectorCostAwareStageSpec)
    assert stage.respect_run_budget is True
    assert stage.respect_tenant_quota is True


def test_cost_aware_stage_valid_full_spec() -> None:
    """A fully specified valid cost-aware stage is parsed without error."""
    errors: list[str] = []
    spec = parse_selector_section(
        {
            "pipeline": [
                {
                    "kind": "cost-aware",
                    "objective": "minimize_cost",
                    "respect": {"run_budget": False, "tenant_quota": False},
                }
            ]
        },
        errors,
    )
    assert errors == []
    stage = spec.pipeline.stages[0]
    assert isinstance(stage, SelectorCostAwareStageSpec)
    assert stage.respect_run_budget is False
    assert stage.respect_tenant_quota is False


def test_score_weighted_stage_non_dict_weights_records_error() -> None:
    """A non-dict weights value is rejected and the stage gets empty weights."""
    errors: list[str] = []
    spec = parse_selector_section(
        {"pipeline": [{"kind": "score-weighted", "weights": "nope"}]}, errors
    )
    assert any("weights must be an object" in e for e in errors)
    stage = spec.pipeline.stages[0]
    assert isinstance(stage, SelectorScoreWeightedStageSpec)
    assert stage.weights == {}


def test_score_weighted_stage_valid_weights() -> None:
    """Valid numeric weights are coerced to float and keyed by string."""
    errors: list[str] = []
    spec = parse_selector_section(
        {
            "pipeline": [
                {"kind": "score-weighted", "weights": {"quality": 1, "cost": 0.5}}
            ]
        },
        errors,
    )
    assert errors == []
    stage = spec.pipeline.stages[0]
    assert isinstance(stage, SelectorScoreWeightedStageSpec)
    weights = stage.weights
    assert weights == {"quality": 1.0, "cost": 0.5}
    assert all(isinstance(v, float) for v in weights.values())


def test_score_weighted_stage_negative_weight_rejected() -> None:
    """A negative weight value is rejected and defaults to 0.0 for that key."""
    errors: list[str] = []
    spec = parse_selector_section(
        {"pipeline": [{"kind": "score-weighted", "weights": {"quality": -1}}]},
        errors,
    )
    assert any("weights.quality must be a non-negative number" in e for e in errors)
    stage = spec.pipeline.stages[0]
    assert isinstance(stage, SelectorScoreWeightedStageSpec)
    assert stage.weights == {"quality": 0.0}


def test_score_weighted_stage_bool_weight_rejected() -> None:
    """A boolean weight value is rejected (bool is an int subclass, must be excluded)."""
    errors: list[str] = []
    parse_selector_section(
        {"pipeline": [{"kind": "score-weighted", "weights": {"quality": True}}]},
        errors,
    )
    assert any("weights.quality must be a non-negative number" in e for e in errors)


def test_multi_stage_pipeline_preserves_order() -> None:
    """Multiple valid stages are parsed and preserved in document order."""
    errors: list[str] = []
    spec = parse_selector_section(
        {
            "pipeline": [
                {"kind": "capability-matching"},
                {"kind": "cost-aware"},
                {"kind": "score-weighted", "weights": {"a": 1}},
            ]
        },
        errors,
    )
    assert errors == []
    assert len(spec.pipeline.stages) == 3
