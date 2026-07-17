"""Tests for the E4-S3 advanced reasoning strategies.

Covers the story DoD: Reflection reviews and revises (and stops early when the
critique approves); Debate/Tree-of-Thought explores multiple branches and
converges on one; and fan-out is bounded by the budget (cost-ceiling test) so a
wide search fails closed rather than overspending.
"""

from __future__ import annotations

import asyncio

from backend.agents.provider import ScriptedLLMProvider
from backend.reasoning import (
    Budget,
    ReasoningEngine,
    ReasoningInput,
    budget_from_policy,
    default_reasoning_policy,
)
from backend.reasoning.strategies import ReflectionStrategy, TreeOfThoughtStrategy


def _make_input(*, task: str = "solve it", budget: Budget | None = None) -> ReasoningInput:
    """Build a :class:`ReasoningInput` with defaults for tests."""
    policy = default_reasoning_policy()
    return ReasoningInput(
        task=task,
        messages=(),
        tools=(),
        policy=policy,
        budget=budget or budget_from_policy(policy),
    )


def test_reflection_revises_when_critique_finds_issues() -> None:
    """Reflection revises the draft when the critique is not an approval."""
    provider = ScriptedLLMProvider(["draft v1", "needs work: fix the edge case", "draft v2"])
    engine = ReasoningEngine(provider=provider)
    output = asyncio.run(engine.run(ReflectionStrategy(max_revisions=1), _make_input()))
    assert output.stop_reason == "completed"
    assert output.content == "draft v2"
    assert output.usage.steps == 3  # execute + critique + revise


def test_reflection_stops_early_when_critique_approves() -> None:
    """Reflection returns the draft unchanged when the critique approves it."""
    provider = ScriptedLLMProvider(["the draft", "LGTM, no issues"])
    engine = ReasoningEngine(provider=provider)
    output = asyncio.run(engine.run(ReflectionStrategy(max_revisions=2), _make_input()))
    assert output.stop_reason == "completed"
    assert output.content == "the draft"
    assert output.usage.steps == 2  # execute + one approving critique, no revise


def test_tot_explores_branches_and_converges() -> None:
    """Tree-of-Thought expands branches and converges on a single best thought."""
    provider = ScriptedLLMProvider(["short", "a longer candidate thought", "mid one"])
    engine = ReasoningEngine(provider=provider)
    output = asyncio.run(engine.run(TreeOfThoughtStrategy(branches=3), _make_input()))
    assert output.stop_reason == "completed"
    # Highest-scoring (longest) candidate wins the beam.
    assert output.content == "a longer candidate thought"
    assert output.usage.steps == 3


def test_tot_fan_out_is_budget_bounded() -> None:
    """A wide Tree-of-Thought fan-out fails closed at the step ceiling."""
    provider = ScriptedLLMProvider(["thought"])
    engine = ReasoningEngine(provider=provider)
    budget = Budget(tokens=10_000, cost_usd=100.0, wall_clock_ms=60_000, max_steps=2)
    output = asyncio.run(engine.run(TreeOfThoughtStrategy(branches=5), _make_input(budget=budget)))
    assert output.stop_reason == "budget_exhausted"
    # Fail-closed: exactly max_steps expansions occurred, none past the ceiling.
    assert output.usage.steps == 2
    assert provider.calls == 2
