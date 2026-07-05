"""Budget arithmetic shared by the Flow Engine and composite node handlers.

Implements the budget-propagation semantics recorded in ADR-006: a child run's
effective budget is the element-wise minimum of its own manifest budgets and
the budget cap its parent computed from its remaining budget at spawn time.
Caps persist in the child run's durable state (``state["budget_cap"]``) so a
resumed execution enforces the same limits.
"""

from __future__ import annotations

from typing import Any

from backend.flows.model import FlowBudgets


def merge_budgets(budgets: FlowBudgets, cap: FlowBudgets) -> FlowBudgets:
    """Combine two budgets, keeping the stricter limit per dimension.

    Args:
        budgets: Base budgets (e.g. a flow manifest's declared budgets).
        cap: Budget cap to apply (e.g. a parent's remaining budget).

    Returns:
        A :class:`FlowBudgets` with the element-wise minimum of both inputs.
    """
    return FlowBudgets(
        max_cost_usd=min(budgets.max_cost_usd, cap.max_cost_usd),
        max_wall_clock_sec=min(budgets.max_wall_clock_sec, cap.max_wall_clock_sec),
        max_tokens=min(budgets.max_tokens, cap.max_tokens),
    )


def budget_cap_document(cap: FlowBudgets) -> dict[str, Any]:
    """Serialize a budget cap for storage in a run's durable state.

    Args:
        cap: Budget cap to serialize.

    Returns:
        A JSON-serializable dict stored under ``state["budget_cap"]``.
    """
    return {
        "max_cost_usd": cap.max_cost_usd,
        "max_wall_clock_sec": cap.max_wall_clock_sec,
        "max_tokens": cap.max_tokens,
    }


def budget_cap_from_state(state: dict[str, Any]) -> FlowBudgets | None:
    """Read a persisted budget cap back from a run's durable state.

    Args:
        state: The run's durable state document.

    Returns:
        The persisted cap, or ``None`` when the run has no cap.
    """
    document = state.get("budget_cap")
    if not isinstance(document, dict):
        return None
    defaults = FlowBudgets()
    return FlowBudgets(
        max_cost_usd=float(document.get("max_cost_usd", defaults.max_cost_usd)),
        max_wall_clock_sec=int(
            document.get("max_wall_clock_sec", defaults.max_wall_clock_sec)
        ),
        max_tokens=int(document.get("max_tokens", defaults.max_tokens)),
    )


def effective_budgets(
    budgets: FlowBudgets,
    state: dict[str, Any],
    budget_cap: FlowBudgets | None = None,
) -> FlowBudgets:
    """Compute the budgets a run execution actually enforces.

    Combines the manifest budgets, any cap persisted in the run state, and an
    explicit caller-provided cap; the strictest limit wins per dimension
    (ADR-006 fail-closed capping).

    Args:
        budgets: The flow manifest's declared budgets.
        state: The run's durable state (may carry ``budget_cap``).
        budget_cap: Optional additional cap supplied by the caller.

    Returns:
        The effective :class:`FlowBudgets` for this execution.
    """
    effective = budgets
    persisted = budget_cap_from_state(state)
    if persisted is not None:
        effective = merge_budgets(effective, persisted)
    if budget_cap is not None:
        effective = merge_budgets(effective, budget_cap)
    return effective


def budget_violation(
    budgets: FlowBudgets,
    state: dict[str, Any],
    elapsed: float,
    activations: int,
    max_steps: int,
) -> str | None:
    """Check run budgets, returning a violation description if any.

    Args:
        budgets: The effective budgets enforced for this execution.
        state: Run state carrying accumulated metrics.
        elapsed: Wall-clock seconds since this execution session began.
        activations: Node activations performed in this session.
        max_steps: Engine safety cap on activations per run.

    Returns:
        A human-readable violation, or ``None`` when within budget.
    """
    if elapsed > budgets.max_wall_clock_sec:
        return (
            f"wall clock {elapsed:.1f}s exceeded budget "
            f"{budgets.max_wall_clock_sec}s"
        )
    metrics = state.get("metrics", {})
    if float(metrics.get("tokens", 0.0)) > budgets.max_tokens:
        return f"tokens {metrics.get('tokens')} exceeded budget {budgets.max_tokens}"
    if float(metrics.get("cost_usd", 0.0)) > budgets.max_cost_usd:
        return (
            f"cost {metrics.get('cost_usd')} exceeded budget "
            f"{budgets.max_cost_usd} USD"
        )
    if activations >= max_steps:
        return f"engine step cap {max_steps} reached"
    return None


__all__ = [
    "budget_cap_document",
    "budget_cap_from_state",
    "budget_violation",
    "effective_budgets",
    "merge_budgets",
]
