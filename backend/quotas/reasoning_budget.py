"""Narrow a Reasoning Engine :class:`Budget` by a tenant's run budget (E11-S3, ADR-019).

Bridges two independently evolved budget shapes: :class:`RunBudgetLimits`
(``backend.quotas.contracts``, integer micro-USD, every field optional —
``None`` means "no tenant limit on this dimension") and :class:`Budget`
(``backend.reasoning.contract``, float USD, every field always set — the
Reasoning Engine's own fail-closed ceiling, E4-S1). Mirrors
:func:`~backend.quotas.contracts.narrow_budget`'s "a child can only narrow
a parent, never widen it" rule across the two types.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.quotas.contracts import MICROS_PER_USD, RunBudgetLimits

if TYPE_CHECKING:
    from backend.reasoning.contract import Budget


def narrow_reasoning_budget(default_run_budget: RunBudgetLimits, requested: Budget) -> Budget:
    """Return ``requested``, tightened by any tenant limit that is stricter.

    Args:
        default_run_budget: The tenant's per-run ceiling (E11-S3). A field
            left ``None`` imposes no additional limit on that dimension —
            ``requested`` governs it unchanged.
        requested: The run's own budget, already resolved from its
            :class:`~backend.reasoning.policy.ReasoningPolicy`
            (``backend.reasoning.engine.budget_from_policy``).

    Returns:
        A new :class:`Budget`, no looser than either input on any dimension.
    """
    # Local import: backend.reasoning's package __init__ eagerly imports
    # ReasoningService, which imports this module -- importing Budget at
    # module level here would circle straight back into that partially
    # initialized package.
    from backend.reasoning.contract import Budget

    tokens = requested.tokens
    if default_run_budget.max_tokens is not None:
        tokens = min(tokens, default_run_budget.max_tokens)

    cost_usd = requested.cost_usd
    if default_run_budget.max_cost_microusd is not None:
        cost_usd = min(cost_usd, default_run_budget.max_cost_microusd / MICROS_PER_USD)

    wall_clock_ms = requested.wall_clock_ms
    if default_run_budget.max_wall_clock_ms is not None:
        wall_clock_ms = min(wall_clock_ms, default_run_budget.max_wall_clock_ms)

    max_steps = requested.max_steps
    if default_run_budget.max_steps is not None:
        max_steps = min(max_steps, default_run_budget.max_steps)

    return Budget(tokens=tokens, cost_usd=cost_usd, wall_clock_ms=wall_clock_ms, max_steps=max_steps)


__all__ = ["narrow_reasoning_budget"]
