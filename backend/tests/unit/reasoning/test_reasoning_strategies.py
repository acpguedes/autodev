"""Tests for the E4-S2 reference reasoning strategies.

Covers the story DoD: every reference strategy runs through the Reasoning
Engine and produces a valid output; strategies are swappable without changing
the caller; the ReAct tool loop dispatches tools and terminates on FINAL; and
budgets fail closed for a non-terminating strategy. The offline
:class:`StubLLMProvider` (and a small scripted provider) keep the tests
deterministic.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

from backend.agents.provider import ScriptedLLMProvider, StubLLMProvider
from backend.reasoning import (
    Budget,
    ReasoningEngine,
    ReasoningInput,
    ReasoningStrategyRegistry,
    ToolSpec,
    budget_from_policy,
    default_reasoning_policy,
)
from backend.reasoning.strategies import (
    NativeToolsStrategy,
    PlanExecuteStrategy,
    ReActStrategy,
    builtin_strategies,
    register_builtin_strategies,
)

BUILTIN_IDS = {
    "autodev/reasoning-react",
    "autodev/reasoning-plan-execute",
    "autodev/reasoning-native-tools",
    "autodev/reasoning-reflection",
    "autodev/reasoning-tot",
}


def _make_input(
    *,
    task: str = "solve it",
    budget: Budget | None = None,
    tools: Sequence[ToolSpec] = (),
) -> ReasoningInput:
    """Build a :class:`ReasoningInput` with defaults for tests."""
    policy = default_reasoning_policy()
    return ReasoningInput(
        task=task,
        messages=(),
        tools=tools,
        policy=policy,
        budget=budget or budget_from_policy(policy),
    )


def test_every_reference_strategy_completes() -> None:
    """Each built-in strategy runs end-to-end and completes."""
    engine = ReasoningEngine(provider=StubLLMProvider(text="FINAL: the answer", tokens_output=2))
    for strategy in builtin_strategies():
        output = asyncio.run(engine.run(strategy, _make_input()))
        assert output.stop_reason == "completed", strategy.id
        assert output.content


def test_strategies_are_swappable() -> None:
    """Different strategies run on the same input without caller changes."""
    engine = ReasoningEngine(provider=StubLLMProvider(text="FINAL: done"))
    run_input = _make_input()
    react = asyncio.run(engine.run(ReActStrategy(), run_input))
    plan = asyncio.run(engine.run(PlanExecuteStrategy(), run_input))
    native = asyncio.run(engine.run(NativeToolsStrategy(), run_input))
    assert react.stop_reason == plan.stop_reason == native.stop_reason == "completed"


def test_react_dispatches_tools_and_terminates() -> None:
    """ReAct dispatches an ACTION to a tool, then terminates on FINAL."""
    provider = ScriptedLLMProvider(["ACTION search kittens", "FINAL got it"])
    engine = ReasoningEngine(provider=provider, tool_impls={"search": lambda args: "found"})
    output = asyncio.run(engine.run(ReActStrategy(), _make_input(tools=(ToolSpec("search"),))))
    assert output.stop_reason == "completed"
    assert output.content == "got it"
    # One LLM+tool iteration plus the final LLM call = 3 mediated steps.
    assert output.usage.steps == 3


def test_react_fails_closed_when_never_terminating() -> None:
    """A ReAct loop that never emits FINAL stops on the budget, fail-closed."""
    provider = ScriptedLLMProvider(["ACTION search x"])
    engine = ReasoningEngine(provider=provider, tool_impls={"search": lambda args: "y"})
    budget = Budget(tokens=10_000, cost_usd=100.0, wall_clock_ms=60_000, max_steps=3)
    output = asyncio.run(
        engine.run(ReActStrategy(), _make_input(budget=budget, tools=(ToolSpec("search"),)))
    )
    assert output.stop_reason == "budget_exhausted"
    assert output.usage.steps == 3


def test_register_builtin_strategies() -> None:
    """Registering the built-ins exposes all three resolvable strategy ids."""
    registry = ReasoningStrategyRegistry()
    register_builtin_strategies(registry)
    assert set(registry.list_ids()) == BUILTIN_IDS
    assert registry.resolve("autodev/reasoning-react").id == "autodev/reasoning-react"
