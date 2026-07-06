"""Raw-document parsing and validation for the ``selector:`` policy section (E5-S2).

Split out of :mod:`backend.routing.policy_parsing` to keep both modules under
the repository's file-size guideline — mirrors the
:mod:`backend.routing.router`/:mod:`backend.routing.selector` executor split.
This module imports the policy dataclasses from :mod:`backend.routing.policy`
(a one-directional dependency, never the reverse), and is imported by
:mod:`backend.routing.policy_parsing`, never the reverse either (no cycle).

A handful of primitive value-coercion helpers (:func:`_string`,
:func:`_as_dict`, :func:`_non_negative_float`) are intentionally duplicated
from :mod:`backend.routing.policy_parsing` rather than imported, following the
same documented tradeoff :mod:`backend.routing.router` makes for its predicate
matcher: a small amount of duplication between two small, single-purpose
modules is preferable to threading private helpers across a module-size split
that exists only for line-count hygiene.
"""

from __future__ import annotations

from typing import Any

from backend.routing.policy import (
    VALID_COST_OBJECTIVES,
    VALID_SELECTOR_STAGE_KINDS,
    VALID_TIE_BREAKERS,
    SelectorCapabilityMatchingStageSpec,
    SelectorCostAwareStageSpec,
    SelectorPipelineSpec,
    SelectorPolicySpec,
    SelectorScoreWeightedStageSpec,
    SelectorStageSpec,
)


def parse_selector_section(raw: Any, errors: list[str]) -> SelectorPolicySpec:
    """Parse and validate the ``selector`` section of a raw policy document.

    The section is optional: an absent ``selector`` key parses to an empty
    pipeline with no error (mirrors the E5-S1 permissiveness established for
    this section, before it had a typed shape).

    Args:
        raw: Raw value of the ``selector`` field, or ``None`` if absent.
        errors: Error list to append validation failures to.

    Returns:
        The parsed :class:`SelectorPolicySpec`; an empty pipeline if ``raw``
        is absent or not an object.
    """
    if raw is None:
        return SelectorPolicySpec()
    if not isinstance(raw, dict):
        errors.append("selector must be an object")
        return SelectorPolicySpec(raw={})

    pipeline_raw = raw.get("pipeline", [])
    if not isinstance(pipeline_raw, list):
        errors.append("selector.pipeline must be a list")
        pipeline_raw = []
    parsed_stages = [_parse_selector_stage(item, index, errors) for index, item in enumerate(pipeline_raw)]
    stages: tuple[SelectorStageSpec, ...] = tuple(stage for stage in parsed_stages if stage is not None)

    tie_breaker = _string(raw.get("tie_breaker", "lowest_cost")) or "lowest_cost"
    if tie_breaker not in VALID_TIE_BREAKERS:
        errors.append(f"selector.tie_breaker must be one of {sorted(VALID_TIE_BREAKERS)}")
        tie_breaker = "lowest_cost"

    return SelectorPolicySpec(
        pipeline=SelectorPipelineSpec(stages=stages, tie_breaker=tie_breaker),
        raw=_as_dict(raw),
    )


def _parse_selector_stage(raw: Any, index: int, errors: list[str]) -> SelectorStageSpec | None:
    """Parse and validate a single ``selector.pipeline`` entry.

    Args:
        raw: Raw value of the pipeline entry.
        index: Position of the entry, used in error messages.
        errors: Error list to append validation failures to.

    Returns:
        The parsed stage spec, or ``None`` if the entry is invalid (the error
        is still recorded).
    """
    prefix = f"selector.pipeline[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{prefix} must be an object")
        return None
    kind = _string(raw.get("kind"))
    if kind not in VALID_SELECTOR_STAGE_KINDS:
        errors.append(f"{prefix}.kind must be one of {sorted(VALID_SELECTOR_STAGE_KINDS)}")
        return None
    if kind == "capability-matching":
        return _parse_capability_matching_stage(raw, prefix, errors)
    if kind == "cost-aware":
        return _parse_cost_aware_stage(raw, prefix, errors)
    return _parse_score_weighted_stage(raw, prefix, errors)


def _parse_capability_matching_stage(
    raw: dict[str, Any], prefix: str, errors: list[str]
) -> SelectorCapabilityMatchingStageSpec:
    """Parse a ``kind: capability-matching`` selector pipeline stage.

    Args:
        raw: Raw stage mapping.
        prefix: Dotted path prefix for error messages.
        errors: Error list to append validation failures to.

    Returns:
        The parsed :class:`SelectorCapabilityMatchingStageSpec`.
    """
    require_all = raw.get("require_all", True)
    if not isinstance(require_all, bool):
        errors.append(f"{prefix}.require_all must be a boolean")
        require_all = True
    return SelectorCapabilityMatchingStageSpec(require_all=require_all)


def _parse_cost_aware_stage(raw: dict[str, Any], prefix: str, errors: list[str]) -> SelectorCostAwareStageSpec:
    """Parse a ``kind: cost-aware`` selector pipeline stage.

    Args:
        raw: Raw stage mapping.
        prefix: Dotted path prefix for error messages.
        errors: Error list to append validation failures to.

    Returns:
        The parsed :class:`SelectorCostAwareStageSpec`.
    """
    objective = _string(raw.get("objective", "minimize_cost")) or "minimize_cost"
    if objective not in VALID_COST_OBJECTIVES:
        errors.append(f"{prefix}.objective must be one of {sorted(VALID_COST_OBJECTIVES)}")
        objective = "minimize_cost"
    respect_raw = raw.get("respect", {})
    if not isinstance(respect_raw, dict):
        errors.append(f"{prefix}.respect must be an object")
        respect_raw = {}
    respect_run_budget = respect_raw.get("run_budget", True)
    if not isinstance(respect_run_budget, bool):
        errors.append(f"{prefix}.respect.run_budget must be a boolean")
        respect_run_budget = True
    respect_tenant_quota = respect_raw.get("tenant_quota", True)
    if not isinstance(respect_tenant_quota, bool):
        errors.append(f"{prefix}.respect.tenant_quota must be a boolean")
        respect_tenant_quota = True
    return SelectorCostAwareStageSpec(
        objective=objective,
        respect_run_budget=respect_run_budget,
        respect_tenant_quota=respect_tenant_quota,
    )


def _parse_score_weighted_stage(raw: dict[str, Any], prefix: str, errors: list[str]) -> SelectorScoreWeightedStageSpec:
    """Parse a ``kind: score-weighted`` selector pipeline stage.

    Args:
        raw: Raw stage mapping.
        prefix: Dotted path prefix for error messages.
        errors: Error list to append validation failures to.

    Returns:
        The parsed :class:`SelectorScoreWeightedStageSpec`.
    """
    weights_raw = raw.get("weights", {})
    if not isinstance(weights_raw, dict):
        errors.append(f"{prefix}.weights must be an object")
        return SelectorScoreWeightedStageSpec(weights={})
    weights: dict[str, float] = {}
    for key, value in weights_raw.items():
        weights[str(key)] = _non_negative_float(value, f"{prefix}.weights.{key}", errors)
    return SelectorScoreWeightedStageSpec(weights=weights)


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce a value to a dict, defaulting to empty when not a mapping.

    Args:
        value: Value to coerce.

    Returns:
        ``value`` if it is already a ``dict``, otherwise ``{}``.
    """
    return dict(value) if isinstance(value, dict) else {}


def _string(value: Any) -> str:
    """Coerce a value to a string, defaulting to empty when not a string.

    Args:
        value: Value to coerce.

    Returns:
        ``value`` if it is already a ``str``, otherwise an empty string.
    """
    return value if isinstance(value, str) else ""


def _non_negative_float(value: Any, field_name: str, errors: list[str]) -> float:
    """Validate a policy field as a non-negative number.

    Args:
        value: Raw field value.
        field_name: Dotted field name, used in error messages.
        errors: Error list to append validation failures to.

    Returns:
        ``value`` as a ``float`` if non-negative, otherwise ``0.0``.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        errors.append(f"{field_name} must be a non-negative number")
        return 0.0
    return float(value)


__all__ = ["parse_selector_section"]
