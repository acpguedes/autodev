"""Agent Runtime binding for the Reasoning Engine (E4-S4).

Provides the seam by which the Agent Runtime (E2) drives a reasoning strategy:
it maps an agent's :class:`~backend.agents.manifest.AgentBudgets` onto a reasoning
:class:`~backend.reasoning.contract.Budget` (run > agent > policy precedence,
reference §8.4) and builds a :class:`~backend.reasoning.contract.ReasoningInput`.
The Agent Runtime then runs it through a
:class:`~backend.reasoning.service.ReasoningService`. Kept as a dedicated adapter
so the Agent Runtime module is not enlarged and the mapping is independently
testable; progressive adoption in the default agent cycle is future work (E5/E14).
"""

from __future__ import annotations

from typing import Any, Sequence

from backend.agents.manifest import AgentBudgets
from backend.reasoning.contract import Budget, ReasoningInput, ToolSpec
from backend.reasoning.policy import ReasoningPolicy


def budget_from_agent_budgets(budgets: AgentBudgets) -> Budget:
    """Map an agent's budgets onto a reasoning :class:`Budget`.

    Args:
        budgets: The agent run's budgets (split input/output tokens, seconds).

    Returns:
        A reasoning :class:`Budget` with a combined token ceiling and
        millisecond wall-clock ceiling.
    """
    return Budget(
        tokens=budgets.tokens_input + budgets.tokens_output,
        cost_usd=budgets.cost_usd,
        wall_clock_ms=budgets.wall_clock_seconds * 1000,
        max_steps=budgets.max_steps,
    )


def reasoning_input_from_agent(
    *,
    task: str,
    policy: ReasoningPolicy,
    budgets: AgentBudgets,
    messages: Sequence[dict[str, Any]] = (),
    tools: Sequence[ToolSpec] = (),
    seed: int | None = None,
) -> ReasoningInput:
    """Build a :class:`ReasoningInput` for an agent run.

    Args:
        task: The task/objective for the reasoning run.
        policy: The reasoning policy in force.
        budgets: The agent run's budgets, mapped to the reasoning budget.
        messages: Session history to pass to the strategy.
        tools: Tools/skills available to the strategy this run.
        seed: Optional seed for deterministic replay.

    Returns:
        A ready-to-run :class:`ReasoningInput`.
    """
    return ReasoningInput(
        task=task,
        messages=tuple(messages),
        tools=tuple(tools),
        policy=policy,
        budget=budget_from_agent_budgets(budgets),
        seed=seed,
    )


__all__ = ["budget_from_agent_budgets", "reasoning_input_from_agent"]
