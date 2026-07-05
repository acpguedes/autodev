"""``reasoning-policy.yaml`` parsing and validation (E4-S1).

A reasoning policy is a declarative, versioned document that governs strategy
selection, budgets, guardrails, and tracing for reasoning runs. See
``docs/architecture/v2_platform_reference.md`` §8.4 for the canonical (pt-BR)
specification this module implements.

This module has no dependency on :mod:`backend.reasoning.contract` (which
imports :class:`ReasoningPolicy` from here) to avoid a circular import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

POLICY_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

#: Valid values for :attr:`GuardrailSpec.on_violation`, per reference §8.5.
VALID_ON_VIOLATION = frozenset({"block", "repair_once", "warn"})

#: Valid values for :attr:`TracingSpec.level`, per reference §8.6.
VALID_TRACING_LEVELS = frozenset({"full", "steps", "summary"})


@dataclass(frozen=True)
class SelectionRule:
    """A single conditional strategy-selection rule.

    Attributes:
        when: Exact-match context predicate (key/value pairs).
        use: Strategy id to select when ``when`` matches.
        config: Strategy-specific configuration to apply when selected.
    """

    when: dict[str, Any]
    use: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SelectionSpec:
    """Strategy-selection configuration.

    Attributes:
        default: Strategy id used when no rule matches.
        rules: Ordered conditional rules, evaluated first-match-wins.
    """

    default: str
    rules: tuple[SelectionRule, ...] = ()


@dataclass(frozen=True)
class ReasoningBudgetPolicy:
    """Declarative budget ceiling and overrun behavior.

    Attributes:
        tokens: Maximum total tokens allowed.
        cost_usd: Maximum cost in US dollars allowed.
        wall_clock_ms: Maximum wall-clock duration allowed, in milliseconds.
        max_steps: Maximum number of mediated calls allowed.
        on_exceed: Either the literal ``"fail_closed"`` or
            ``"degrade_to:<strategy-id>"``.
    """

    tokens: int
    cost_usd: float
    wall_clock_ms: int
    max_steps: int
    on_exceed: str = "fail_closed"


@dataclass(frozen=True)
class GuardrailSpec:
    """A single guardrail entry in a reasoning policy.

    Attributes:
        id: Identifier of the guardrail to evaluate (e.g. ``"schema_conformance"``).
        on_violation: One of :data:`VALID_ON_VIOLATION`.
    """

    id: str
    on_violation: str


@dataclass(frozen=True)
class TracingSpec:
    """Telemetry/replay configuration for a reasoning policy.

    Attributes:
        level: One of :data:`VALID_TRACING_LEVELS`.
        record_prompts: Whether prompts/responses are recorded in the trace.
        deterministic_replay: Whether the run must be deterministically
            replayable from its trace.
    """

    level: str = "full"
    record_prompts: bool = True
    deterministic_replay: bool = True


@dataclass(frozen=True)
class ReasoningPolicy:
    """Fully parsed and validated ``reasoning-policy.yaml`` document.

    Attributes:
        schema_version: Policy schema version.
        id: Fully qualified policy id in ``namespace/name`` format.
        version: SemVer version of the policy.
        host_api: Supported host API version range.
        selection: Strategy-selection configuration.
        budget: Budget ceiling and overrun behavior.
        guardrails: Ordered guardrail checks applied to run output.
        tracing: Telemetry/replay configuration.
        raw: Original parsed policy document.
    """

    schema_version: str
    id: str
    version: str
    host_api: str
    selection: SelectionSpec
    budget: ReasoningBudgetPolicy
    guardrails: tuple[GuardrailSpec, ...] = ()
    tracing: TracingSpec = field(default_factory=TracingSpec)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReasoningPolicyValidationResult:
    """Outcome of validating a raw reasoning policy document.

    Attributes:
        valid: Whether the policy passed validation.
        errors: Validation error messages, empty when ``valid`` is ``True``.
        policy: The parsed policy, present only when ``valid`` is ``True``.
    """

    valid: bool
    errors: list[str]
    policy: ReasoningPolicy | None = None


def validate_reasoning_policy(raw: dict[str, Any]) -> ReasoningPolicyValidationResult:
    """Validate a raw policy document and parse it into a :class:`ReasoningPolicy`.

    Args:
        raw: Parsed ``reasoning-policy.yaml`` document, keyed by camelCase
            field names.

    Returns:
        A result indicating whether the policy is valid; on success it
        carries the parsed :class:`ReasoningPolicy`, on failure the list of
        error messages.
    """
    errors: list[str] = []
    for key in ("schemaVersion", "id", "version", "hostApi", "selection", "budget"):
        if key not in raw:
            errors.append(f"{key} is required")

    schema_version = _string(raw.get("schemaVersion")) or str(raw.get("schemaVersion", ""))
    policy_id = _string(raw.get("id"))
    version = _string(raw.get("version"))
    host_api = _string(raw.get("hostApi"))

    if policy_id and not POLICY_ID_RE.match(policy_id):
        errors.append("id must use namespace/name kebab-case format")
    if version and not _is_semver(version):
        errors.append("version must be SemVer MAJOR.MINOR.PATCH")
    if host_api and not _is_supported_range(host_api):
        errors.append("hostApi must be a supported range expression")

    selection = _parse_selection(raw.get("selection"), errors)
    budget = _parse_budget(raw.get("budget"), errors)
    guardrails = _parse_guardrails(raw.get("guardrails", []), errors)
    tracing = _parse_tracing(raw.get("tracing", {}), errors)

    if errors:
        return ReasoningPolicyValidationResult(False, errors)

    return ReasoningPolicyValidationResult(
        True,
        [],
        ReasoningPolicy(
            schema_version=schema_version,
            id=policy_id,
            version=version,
            host_api=host_api,
            selection=selection,
            budget=budget,
            guardrails=tuple(guardrails),
            tracing=tracing,
            raw=dict(raw),
        ),
    )


def load_reasoning_policy(path: Path | str) -> ReasoningPolicy:
    """Load and validate a ``reasoning-policy.yaml`` document from disk.

    Args:
        path: Path to the ``reasoning-policy.yaml`` file.

    Returns:
        The parsed and validated :class:`ReasoningPolicy`.

    Raises:
        ValueError: If the document is not a mapping or fails validation.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("reasoning-policy.yaml must contain a mapping at the document root")
    result = validate_reasoning_policy(raw)
    if not result.valid or result.policy is None:
        raise ValueError("; ".join(result.errors))
    return result.policy


def select_strategy(policy: ReasoningPolicy, context: dict[str, Any] | None = None) -> str:
    """Resolve the reasoning strategy id to use for a run.

    This is an intentionally minimal E4-S1 stub: it matches a rule only when
    every key in ``rule.when`` is present in ``context`` with an exactly
    equal value. It does not support the comparison operators shown in the
    reference doc's example policy (e.g. ``"complexity: >=high"``) or
    integration with the Router & Selector service — full declarative,
    operator-aware selection is E4-S4 scope.

    Args:
        policy: The reasoning policy to select from.
        context: Task/run context to match selection rules against. When
            omitted or empty, the policy's default strategy is returned.

    Returns:
        The selected strategy id.
    """
    if context:
        for rule in policy.selection.rules:
            if all(context.get(key) == value for key, value in rule.when.items()):
                return rule.use
    return policy.selection.default


def _parse_selection(raw: Any, errors: list[str]) -> SelectionSpec:
    """Parse and validate the ``selection`` section of a raw policy.

    Args:
        raw: Raw value of the ``selection`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed selection spec; empty default if ``raw`` is not an object.
    """
    if not isinstance(raw, dict):
        errors.append("selection must be an object")
        return SelectionSpec(default="")
    default = _string(raw.get("default"))
    if not default:
        errors.append("selection.default is required")
    rules_raw = raw.get("rules", [])
    if rules_raw is not None and not isinstance(rules_raw, list):
        errors.append("selection.rules must be a list")
        rules_raw = []
    rules: list[SelectionRule] = []
    for index, item in enumerate(rules_raw or []):
        prefix = f"selection.rules[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        when = item.get("when")
        use = _string(item.get("use"))
        if not isinstance(when, dict) or not when:
            errors.append(f"{prefix}.when must be a non-empty object")
            continue
        if not use:
            errors.append(f"{prefix}.use is required")
            continue
        config = item.get("config", {})
        if config is not None and not isinstance(config, dict):
            errors.append(f"{prefix}.config must be an object")
            config = {}
        rules.append(SelectionRule(when=dict(when), use=use, config=dict(config or {})))
    return SelectionSpec(default=default, rules=tuple(rules))


def _parse_budget(raw: Any, errors: list[str]) -> ReasoningBudgetPolicy:
    """Parse and validate the ``budget`` section of a raw policy.

    Args:
        raw: Raw value of the ``budget`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed budget policy; zeroed defaults if ``raw`` is not an object.
    """
    if not isinstance(raw, dict):
        errors.append("budget must be an object")
        return ReasoningBudgetPolicy(tokens=0, cost_usd=0.0, wall_clock_ms=0, max_steps=0)
    tokens = _positive_int(raw.get("tokens"), "budget.tokens", errors)
    cost_usd = _positive_float(raw.get("cost_usd"), "budget.cost_usd", errors)
    wall_clock_ms = _positive_int(raw.get("wall_clock_ms"), "budget.wall_clock_ms", errors)
    max_steps = _positive_int(raw.get("max_steps"), "budget.max_steps", errors)
    on_exceed = _string(raw.get("on_exceed", "fail_closed")) or "fail_closed"
    if on_exceed != "fail_closed" and not on_exceed.startswith("degrade_to:"):
        errors.append("budget.on_exceed must be 'fail_closed' or 'degrade_to:<strategy-id>'")
    return ReasoningBudgetPolicy(
        tokens=tokens, cost_usd=cost_usd, wall_clock_ms=wall_clock_ms, max_steps=max_steps, on_exceed=on_exceed
    )


def _parse_guardrails(raw: Any, errors: list[str]) -> list[GuardrailSpec]:
    """Parse and validate the ``guardrails`` section of a raw policy.

    Args:
        raw: Raw value of the ``guardrails`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed guardrail specs; empty if ``raw`` is absent or invalid.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append("guardrails must be a list")
        return []
    guardrails: list[GuardrailSpec] = []
    for index, item in enumerate(raw):
        prefix = f"guardrails[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        guardrail_id = _string(item.get("id"))
        on_violation = _string(item.get("on_violation"))
        if not guardrail_id:
            errors.append(f"{prefix}.id is required")
            continue
        if on_violation not in VALID_ON_VIOLATION:
            errors.append(f"{prefix}.on_violation must be one of {sorted(VALID_ON_VIOLATION)}")
            continue
        guardrails.append(GuardrailSpec(id=guardrail_id, on_violation=on_violation))
    return guardrails


def _parse_tracing(raw: Any, errors: list[str]) -> TracingSpec:
    """Parse and validate the ``tracing`` section of a raw policy.

    Args:
        raw: Raw value of the ``tracing`` field.
        errors: Error list to append validation failures to.

    Returns:
        Parsed tracing spec; defaults if ``raw`` is empty or not an object.
    """
    if raw in (None, {}):
        return TracingSpec()
    if not isinstance(raw, dict):
        errors.append("tracing must be an object")
        return TracingSpec()
    level = _string(raw.get("level", "full")) or "full"
    if level not in VALID_TRACING_LEVELS:
        errors.append(f"tracing.level must be one of {sorted(VALID_TRACING_LEVELS)}")
        level = "full"
    record_prompts = raw.get("record_prompts", True)
    deterministic_replay = raw.get("deterministic_replay", True)
    if not isinstance(record_prompts, bool):
        errors.append("tracing.record_prompts must be a boolean")
        record_prompts = True
    if not isinstance(deterministic_replay, bool):
        errors.append("tracing.deterministic_replay must be a boolean")
        deterministic_replay = True
    return TracingSpec(level=level, record_prompts=record_prompts, deterministic_replay=deterministic_replay)


def _string(value: Any) -> str:
    """Coerce a value to a string, defaulting to empty when not a string.

    Args:
        value: Value to coerce.

    Returns:
        ``value`` if it is already a ``str``, otherwise an empty string.
    """
    return value if isinstance(value, str) else ""


def _positive_int(value: Any, field_name: str, errors: list[str]) -> int:
    """Validate a policy field as a positive integer.

    Args:
        value: Raw field value.
        field_name: Dotted field name, used in error messages.
        errors: Error list to append validation failures to.

    Returns:
        ``value`` if it is a positive integer, otherwise ``0``.
    """
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        errors.append(f"{field_name} must be a positive integer")
        return 0
    return value


def _positive_float(value: Any, field_name: str, errors: list[str]) -> float:
    """Validate a policy field as a positive number.

    Args:
        value: Raw field value.
        field_name: Dotted field name, used in error messages.
        errors: Error list to append validation failures to.

    Returns:
        ``value`` as a ``float`` if it is a positive number, otherwise ``0.0``.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        errors.append(f"{field_name} must be a positive number")
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


DEFAULT_REASONING_POLICY_ID = "autodev/reasoning-policy-default"


def default_reasoning_policy(
    *,
    default_strategy: str = "autodev/reasoning-react",
    tokens: int = 24000,
    cost_usd: float = 0.75,
    wall_clock_ms: int = 45000,
    max_steps: int = 12,
    guardrails: tuple[GuardrailSpec, ...] = (),
) -> ReasoningPolicy:
    """Build a permissive default reasoning policy (reference §8.4 defaults).

    Args:
        default_strategy: Strategy id selected when no selection rule matches.
        tokens: Maximum total tokens allowed.
        cost_usd: Maximum cost in US dollars allowed.
        wall_clock_ms: Maximum wall-clock duration allowed, in milliseconds.
        max_steps: Maximum number of mediated calls allowed.
        guardrails: Guardrail specs to apply to run output.

    Returns:
        A ready-to-use :class:`ReasoningPolicy`.
    """
    return ReasoningPolicy(
        schema_version="1",
        id=DEFAULT_REASONING_POLICY_ID,
        version="1.0.0",
        host_api=">=2.0 <3.0",
        selection=SelectionSpec(default=default_strategy),
        budget=ReasoningBudgetPolicy(
            tokens=tokens, cost_usd=cost_usd, wall_clock_ms=wall_clock_ms, max_steps=max_steps
        ),
        guardrails=tuple(guardrails),
        tracing=TracingSpec(),
    )


__all__ = [
    "DEFAULT_REASONING_POLICY_ID",
    "default_reasoning_policy",
    "GuardrailSpec",
    "POLICY_ID_RE",
    "ReasoningBudgetPolicy",
    "ReasoningPolicy",
    "ReasoningPolicyValidationResult",
    "SelectionRule",
    "SelectionSpec",
    "TracingSpec",
    "VALID_ON_VIOLATION",
    "VALID_TRACING_LEVELS",
    "load_reasoning_policy",
    "select_strategy",
    "validate_reasoning_policy",
]
