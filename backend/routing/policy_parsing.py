"""Raw-document parsing and validation for ``routing-policy.yaml`` (E5-S1, E5-S2).

Split out of :mod:`backend.routing.policy` to keep both modules under the
repository's file-size guideline. This module imports the policy dataclasses
from there — a one-directional dependency (this module depends on
``policy.py``, never the reverse), so there is no import cycle.

This module parses the ``router:`` section. Parsing of the ``selector:``
section is split out further into :mod:`backend.routing.selector_policy_parsing`
(E5-S2) — the same file-size-guideline rationale, mirroring the
:mod:`backend.routing.router`/:mod:`backend.routing.selector` executor split.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from backend.routing.policy import (
    VALID_LATENCY_CLASSES,
    VALID_ROUTER_STAGE_KINDS,
    RouteConstraintsSpec,
    RouterDefaultSpec,
    RouterEmbeddingsStageSpec,
    RouterLLMStageSpec,
    RouterPipelineSpec,
    RouterRuleSpec,
    RouterRulesStageSpec,
    RouterStageSpec,
    RoutingPolicy,
    FallbackPolicySpec,
    GuardrailsPolicySpec,
    generic_router_default,
)
from backend.routing.selector_policy_parsing import parse_selector_section

POLICY_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

#: Regex-operator prefix recognized in a rule's ``when`` predicate values,
#: reused between predicate parsing here and predicate matching in
#: :mod:`backend.routing.router` (kept in sync by the shared ``_OP_RE`` shape;
#: duplicated per that module's documented reuse-vs-duplication tradeoff).
_REGEX_OP_PREFIX = "~="


@dataclass(frozen=True)
class RoutingPolicyValidationResult:
    """Outcome of validating a raw routing policy document.

    Attributes:
        valid: Whether the policy passed validation.
        errors: Validation error messages, empty when ``valid`` is ``True``.
        policy: The parsed policy, present only when ``valid`` is ``True``.
    """

    valid: bool
    errors: list[str]
    policy: RoutingPolicy | None = None


def validate_routing_policy(raw: dict[str, Any]) -> RoutingPolicyValidationResult:
    """Validate a raw policy document and parse it into a :class:`RoutingPolicy`.

    Args:
        raw: Parsed ``routing-policy.yaml`` document, keyed by camelCase field
            names.

    Returns:
        A result indicating whether the policy is valid; on success it carries
        the parsed :class:`RoutingPolicy`, on failure the list of error
        messages.
    """
    errors: list[str] = []
    for key in ("schemaVersion", "id", "version", "hostApi", "router"):
        if key not in raw:
            errors.append(f"{key} is required")

    schema_version = _string(raw.get("schemaVersion")) or str(raw.get("schemaVersion", ""))
    policy_id = _required_string(raw, "id", errors)
    version = _required_string(raw, "version", errors)
    host_api = _required_string(raw, "hostApi", errors)

    if policy_id and not POLICY_ID_RE.match(policy_id):
        errors.append("id must use namespace/name kebab-case format")
    if version and not _is_semver(version):
        errors.append("version must be SemVer MAJOR.MINOR.PATCH")
    if host_api and not _is_supported_range(host_api):
        errors.append("hostApi must be a supported range expression")

    router = _parse_router(raw.get("router"), errors)
    selector = parse_selector_section(raw.get("selector"), errors)
    guardrails = GuardrailsPolicySpec(raw=_as_dict(raw.get("guardrails")))
    fallback = FallbackPolicySpec(raw=_as_dict(raw.get("fallback")))

    if errors:
        return RoutingPolicyValidationResult(False, errors)

    return RoutingPolicyValidationResult(
        True,
        [],
        RoutingPolicy(
            schema_version=schema_version,
            id=policy_id,
            version=version,
            host_api=host_api,
            router=router,
            selector=selector,
            guardrails=guardrails,
            fallback=fallback,
            raw=dict(raw),
        ),
    )


def load_routing_policy(path: Path | str) -> RoutingPolicy:
    """Load and validate a ``routing-policy.yaml`` document from disk.

    Args:
        path: Path to the ``routing-policy.yaml`` file.

    Returns:
        The parsed and validated :class:`RoutingPolicy`.

    Raises:
        ValueError: If the document is not a mapping or fails validation.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("routing-policy.yaml must contain a mapping at the document root")
    result = validate_routing_policy(raw)
    if not result.valid or result.policy is None:
        raise ValueError("; ".join(result.errors))
    return result.policy


def _parse_router(raw: Any, errors: list[str]) -> RouterPipelineSpec:
    """Parse and validate the ``router`` section of a raw policy.

    Args:
        raw: Raw value of the ``router`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed router pipeline spec; an empty pipeline with a generic default
        if ``raw`` is not an object.
    """
    if not isinstance(raw, dict):
        errors.append("router must be an object")
        return RouterPipelineSpec(stages=(), default=generic_router_default())

    pipeline_raw = raw.get("pipeline", [])
    if not isinstance(pipeline_raw, list):
        errors.append("router.pipeline must be a list")
        pipeline_raw = []
    parsed_stages = [_parse_stage(item, index, errors) for index, item in enumerate(pipeline_raw)]
    stages: tuple[RouterStageSpec, ...] = tuple(stage for stage in parsed_stages if stage is not None)

    default_raw = raw.get("default")
    default = _parse_default(default_raw, errors) if default_raw is not None else generic_router_default()

    constraints_raw = raw.get("constraints")
    constraints = _parse_constraints(constraints_raw, "router.constraints", errors) if constraints_raw else RouteConstraintsSpec()

    return RouterPipelineSpec(stages=stages, default=default, constraints=constraints)


def _parse_stage(raw: Any, index: int, errors: list[str]) -> RouterStageSpec | None:
    """Parse and validate a single ``router.pipeline`` entry.

    Args:
        raw: Raw value of the pipeline entry.
        index: Position of the entry, used in error messages.
        errors: Error list to append validation failures to.

    Returns:
        The parsed stage spec, or ``None`` if the entry is invalid (the error
        is still recorded).
    """
    prefix = f"router.pipeline[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{prefix} must be an object")
        return None
    kind = _string(raw.get("kind"))
    if kind not in VALID_ROUTER_STAGE_KINDS:
        errors.append(f"{prefix}.kind must be one of {sorted(VALID_ROUTER_STAGE_KINDS)}")
        return None
    if kind == "rules":
        return _parse_rules_stage(raw, prefix, errors)
    if kind == "embeddings":
        return _parse_embeddings_stage(raw, prefix, errors)
    return _parse_llm_router_stage(raw, prefix, errors)


def _parse_rules_stage(raw: dict[str, Any], prefix: str, errors: list[str]) -> RouterRulesStageSpec:
    """Parse a ``kind: rules`` pipeline stage.

    Args:
        raw: Raw stage mapping.
        prefix: Dotted path prefix for error messages.
        errors: Error list to append validation failures to.

    Returns:
        The parsed :class:`RouterRulesStageSpec`.
    """
    confidence_floor = _float_in_unit_range(raw.get("confidence_floor", 0.0), f"{prefix}.confidence_floor", errors)
    rules_raw = raw.get("rules", [])
    if not isinstance(rules_raw, list):
        errors.append(f"{prefix}.rules must be a list")
        rules_raw = []
    rules: list[RouterRuleSpec] = []
    for rule_index, item in enumerate(rules_raw):
        parsed = _parse_rule(item, f"{prefix}.rules[{rule_index}]", errors)
        if parsed is not None:
            rules.append(parsed)
    return RouterRulesStageSpec(confidence_floor=confidence_floor, rules=tuple(rules))


def _parse_rule(item: Any, prefix: str, errors: list[str]) -> RouterRuleSpec | None:
    """Parse and validate a single ``rules`` stage rule entry.

    Validates the rule's ``when`` predicates (including pre-compiling any
    ``~=`` regex expression so an invalid pattern is caught here, not silently
    swallowed at match time in :mod:`backend.routing.router`), its required
    ``set.task_type``/``set.path``, and its optional ``set.constraints``.

    Args:
        item: Raw rule entry.
        prefix: Dotted path prefix for error messages.
        errors: Error list to append validation failures to.

    Returns:
        The parsed :class:`RouterRuleSpec`, or ``None`` if the entry is
        invalid (the error is still recorded).
    """
    if not isinstance(item, dict):
        errors.append(f"{prefix} must be an object")
        return None
    when = item.get("when")
    set_ = item.get("set")
    if not isinstance(when, dict) or not when:
        errors.append(f"{prefix}.when must be a non-empty object")
        return None
    _validate_when_predicates(when, f"{prefix}.when", errors)
    if not isinstance(set_, dict) or "task_type" not in set_ or "path" not in set_:
        errors.append(f"{prefix}.set must be an object with task_type and path")
        return None
    path_raw = set_.get("path")
    if not isinstance(path_raw, list) or not all(isinstance(node, str) for node in path_raw):
        errors.append(f"{prefix}.set.path must be a list of strings")
        return None
    constraints_raw = set_.get("constraints")
    if constraints_raw is not None:
        _parse_constraints(constraints_raw, f"{prefix}.set.constraints", errors)
    confidence = _float_in_unit_range(item.get("confidence", 1.0), f"{prefix}.confidence", errors)
    return RouterRuleSpec(when=dict(when), set=dict(set_), confidence=confidence)


def _validate_when_predicates(when: dict[str, Any], prefix: str, errors: list[str]) -> None:
    """Pre-compile any ``~=`` regex predicate value to catch bad patterns early.

    Args:
        when: The rule's predicate mapping.
        prefix: Dotted path prefix for error messages.
        errors: Error list to append validation failures to.
    """
    for key, expected in when.items():
        if not isinstance(expected, str) or not expected.strip().startswith(_REGEX_OP_PREFIX):
            continue
        pattern = expected.strip()[len(_REGEX_OP_PREFIX) :].strip()
        if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
            pattern = pattern[1:-1]
        try:
            re.compile(pattern)
        except re.error as exc:
            errors.append(f"{prefix}.{key!r} has an invalid regex pattern: {exc}")


def _parse_embeddings_stage(raw: dict[str, Any], prefix: str, errors: list[str]) -> RouterEmbeddingsStageSpec:
    """Parse a ``kind: embeddings`` pipeline stage.

    Args:
        raw: Raw stage mapping.
        prefix: Dotted path prefix for error messages.
        errors: Error list to append validation failures to.

    Returns:
        The parsed :class:`RouterEmbeddingsStageSpec`.
    """
    dataset = _string(raw.get("dataset"))
    if not dataset:
        errors.append(f"{prefix}.dataset is required")
    threshold = _float_in_unit_range(raw.get("threshold", 0.0), f"{prefix}.threshold", errors)
    return RouterEmbeddingsStageSpec(dataset=dataset, threshold=threshold)


def _parse_llm_router_stage(raw: dict[str, Any], prefix: str, errors: list[str]) -> RouterLLMStageSpec:
    """Parse a ``kind: llm-router`` pipeline stage.

    Args:
        raw: Raw stage mapping.
        prefix: Dotted path prefix for error messages.
        errors: Error list to append validation failures to.

    Returns:
        The parsed :class:`RouterLLMStageSpec`.
    """
    model = _string(raw.get("model"))
    if not model:
        errors.append(f"{prefix}.model is required")
    max_cost_usd = _non_negative_float(raw.get("max_cost_usd", 0.0), f"{prefix}.max_cost_usd", errors)
    only_if_confidence_below = _float_in_unit_range(
        raw.get("only_if_confidence_below", 1.0), f"{prefix}.only_if_confidence_below", errors
    )
    return RouterLLMStageSpec(model=model, max_cost_usd=max_cost_usd, only_if_confidence_below=only_if_confidence_below)


def _parse_default(raw: Any, errors: list[str]) -> RouterDefaultSpec:
    """Parse and validate the ``router.default`` section of a raw policy.

    Args:
        raw: Raw value of the ``router.default`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed default decision spec; a generic fallback if ``raw`` is not an
        object.
    """
    if not isinstance(raw, dict):
        errors.append("router.default must be an object")
        return generic_router_default()
    task_type = _string(raw.get("task_type")) or "unclassified"
    intent = _string(raw.get("intent")) or "unspecified"
    path_raw = raw.get("path", [])
    if not isinstance(path_raw, list):
        errors.append("router.default.path must be a list")
        path_raw = []
    confidence = _float_in_unit_range(raw.get("confidence", 0.0), "router.default.confidence", errors)
    rationale = _string(raw.get("rationale")) or "no pipeline stage matched; using the policy default"
    return RouterDefaultSpec(
        task_type=task_type,
        intent=intent,
        path=tuple(str(node) for node in path_raw),
        confidence=confidence,
        rationale=rationale,
    )


def _parse_constraints(raw: Any, prefix: str, errors: list[str]) -> RouteConstraintsSpec:
    """Parse and validate a ``constraints`` mapping.

    Args:
        raw: Raw value of the ``constraints`` field.
        prefix: Dotted path prefix for error messages.
        errors: Error list to append validation failures to.

    Returns:
        Parsed constraints spec; defaults if ``raw`` is not an object.
    """
    if not isinstance(raw, dict):
        errors.append(f"{prefix} must be an object")
        return RouteConstraintsSpec()
    max_cost_usd = _non_negative_float(raw.get("max_cost_usd", 0.05), f"{prefix}.max_cost_usd", errors)
    latency_class = _string(raw.get("latency_class", "interactive")) or "interactive"
    if latency_class not in VALID_LATENCY_CLASSES:
        errors.append(f"{prefix}.latency_class must be one of {sorted(VALID_LATENCY_CLASSES)}")
        latency_class = "interactive"
    return RouteConstraintsSpec(max_cost_usd=max_cost_usd, latency_class=latency_class)


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


def _required_string(raw: dict[str, Any], key: str, errors: list[str]) -> str:
    """Extract a required top-level string field, flagging a wrong type.

    Distinguishes "absent" (already reported by the caller's required-key
    check) from "present but not a string" (e.g. an unquoted YAML number like
    ``version: 1.0``, which ``yaml.safe_load`` parses as a ``float``) — the
    latter previously fell through the truthiness-based format checks below
    silently, storing an empty string with no validation error.

    Args:
        raw: The raw policy document.
        key: The field name to extract.
        errors: Error list to append validation failures to.

    Returns:
        The field's string value, or ``""`` if absent or wrongly typed.
    """
    if key not in raw:
        return ""
    value = raw[key]
    if not isinstance(value, str):
        errors.append(f"{key} must be a string")
        return ""
    return value


def _float_in_unit_range(value: Any, field_name: str, errors: list[str]) -> float:
    """Validate a policy field as a float in ``[0, 1]``.

    Args:
        value: Raw field value.
        field_name: Dotted field name, used in error messages.
        errors: Error list to append validation failures to.

    Returns:
        ``value`` as a ``float`` if within range, otherwise ``0.0``.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not (0.0 <= float(value) <= 1.0):
        errors.append(f"{field_name} must be a number between 0 and 1")
        return 0.0
    return float(value)


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


def _is_semver(value: str) -> bool:
    """Check whether a string is a valid ``MAJOR.MINOR.PATCH`` SemVer version.

    Args:
        value: Candidate version string.

    Returns:
        ``True`` if ``value`` is a valid SemVer version, ``False`` otherwise.
    """
    if not SEMVER_RE.match(value):
        return False
    try:
        Version(value)
    except InvalidVersion:
        return False
    return True


def _is_supported_range(value: str) -> bool:
    """Check whether a string is a valid version range expression.

    Args:
        value: Candidate range expression, or ``"*"`` for any version.

    Returns:
        ``True`` if ``value`` is ``"*"`` or a valid, non-empty specifier set.
    """
    if value == "*":
        return True
    try:
        SpecifierSet(value.replace(" ", ","))
    except InvalidSpecifier:
        return False
    return bool(value.strip())


__all__ = [
    "POLICY_ID_RE",
    "RoutingPolicyValidationResult",
    "SEMVER_RE",
    "load_routing_policy",
    "validate_routing_policy",
]
