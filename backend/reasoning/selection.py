"""Policy-driven reasoning strategy selection with precedence (E4-S4).

Resolves which strategy a run should use by applying the precedence of
reference §8.7 — platform default < policy rules < Agent Manifest < Flow Node
override < dynamic Selector (E5) — and evaluating the policy's ``selection.rules``
with operator-aware predicates (e.g. ``complexity: ">=high"``,
``budget.tokens: ">=20000"``). The chosen strategy and its source are returned as
a :class:`SelectionDecision` so the decision can be recorded in the trace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.reasoning.policy import ReasoningPolicy

#: Ordinal levels so predicates like ``">=high"`` compare meaningfully.
_LEVELS = {"low": 0.0, "medium": 1.0, "high": 2.0, "critical": 3.0}

_OP_RE = re.compile(r"^(>=|<=|==|>|<)\s*(.+)$")


@dataclass(frozen=True)
class SelectionDecision:
    """The outcome of resolving a strategy for a run.

    Attributes:
        strategy_id: Selected strategy id.
        source: Precedence tier that decided it — one of ``"default"``,
            ``"policy_rule"``, ``"manifest"``, ``"flow_node"``, ``"selector"``.
        config: Strategy configuration to apply (from a matched policy rule).
    """

    strategy_id: str
    source: str
    config: dict[str, Any] = field(default_factory=dict)


def resolve_strategy(
    policy: ReasoningPolicy,
    *,
    context: Mapping[str, Any] | None = None,
    manifest_strategy: str | None = None,
    node_override: str | None = None,
    selector_choice: str | None = None,
) -> SelectionDecision:
    """Resolve the strategy for a run by precedence (reference §8.7).

    Higher-precedence sources win: a dynamic Selector choice overrides a Flow
    Node override, which overrides an Agent Manifest declaration, which overrides
    the policy's rules/default.

    Args:
        policy: The reasoning policy in force.
        context: Task/run signals matched against ``policy.selection.rules``.
        manifest_strategy: Strategy declared on the Agent Manifest, if any.
        node_override: Strategy override from a Flow Node, if any.
        selector_choice: Strategy chosen by the dynamic Selector (E5), if any.

    Returns:
        The :class:`SelectionDecision` naming the strategy and its source.
    """
    if selector_choice:
        return SelectionDecision(selector_choice, "selector")
    if node_override:
        return SelectionDecision(node_override, "flow_node")
    if manifest_strategy:
        return SelectionDecision(manifest_strategy, "manifest")
    signals = context or {}
    for rule in policy.selection.rules:
        if _matches(rule.when, signals):
            return SelectionDecision(rule.use, "policy_rule", dict(rule.config))
    return SelectionDecision(policy.selection.default, "default")


def _matches(when: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    """Return whether every predicate in ``when`` holds for ``context``.

    Args:
        when: Rule predicate mapping (key to expected value/expression).
        context: Run signals to test.

    Returns:
        ``True`` if all predicates match.
    """
    return all(_match_value(context.get(key), expected) for key, expected in when.items())


def _match_value(actual: Any, expected: Any) -> bool:
    """Match a single actual value against an expected value or expression.

    Args:
        actual: The value from the run context (``None`` if absent).
        expected: A literal or an operator expression like ``">=high"``.

    Returns:
        ``True`` if the actual value satisfies the expectation.
    """
    if actual is None:
        return False
    if isinstance(expected, str):
        match = _OP_RE.match(expected.strip())
        if match:
            return _compare(actual, match.group(1), match.group(2).strip())
        return _coerce(actual) == _coerce(expected)
    return bool(actual == expected)


def _compare(actual: Any, operator: str, value: str) -> bool:
    """Apply a comparison operator between an actual value and an expected one.

    Args:
        actual: The value from the run context.
        operator: One of ``>=``, ``<=``, ``==``, ``>``, ``<``.
        value: The right-hand operand as a string.

    Returns:
        The boolean result; ``False`` when the operands are not comparable.
    """
    left: Any = _coerce(actual)
    right: Any = _coerce(value)
    if isinstance(left, float) != isinstance(right, float):
        return False
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    return left == right


def _coerce(value: Any) -> float | str:
    """Coerce a value to a float (number or ordinal level) or a lowercase string.

    Args:
        value: The value to coerce.

    Returns:
        A ``float`` for numbers and known ordinal levels, else a lowercase string.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    key = str(value).strip().lower()
    if key in _LEVELS:
        return _LEVELS[key]
    return key


__all__ = ["SelectionDecision", "resolve_strategy"]
