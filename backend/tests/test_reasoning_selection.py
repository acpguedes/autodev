"""Tests for E4-S4 reasoning policies: selection, budgets, and fallback.

Covers the story DoD: a policy selects the strategy by context (with operator-
aware rules and the reference §8.7 precedence); overrun triggers the declared
``degrade_to`` fallback; the default fails closed; and the policy decision is
traced. Also checks the Agent Runtime binding adapter.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

from backend.agents.manifest import AgentBudgets
from backend.agents.provider import LLMProviderResponse, StubLLMProvider
from backend.reasoning import (
    ReasoningInput,
    ReasoningService,
    ReasoningStrategyRegistry,
    budget_from_agent_budgets,
    budget_from_policy,
    default_reasoning_policy,
    reasoning_input_from_agent,
    resolve_strategy,
)
from backend.reasoning.contract import ToolSpec, TraceEvent
from backend.reasoning.policy import (
    ReasoningBudgetPolicy,
    ReasoningPolicy,
    SelectionRule,
    SelectionSpec,
    TracingSpec,
)
from backend.reasoning.strategies import register_builtin_strategies


class _ScriptedProvider:
    """Provider returning a scripted sequence of completions, then repeating."""

    def __init__(self, responses: Sequence[str]) -> None:
        """Store the scripted responses and initialize the call counter."""
        self._responses = list(responses)
        self.calls = 0

    def complete(self, prompt: str, *, agent_id: str, run_id: str, tenant_id: str) -> LLMProviderResponse:
        """Return the next scripted response (repeating the last one)."""
        index = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return LLMProviderResponse(text=self._responses[index], tokens_input=1, tokens_output=1)


def _policy_with_rules(*, on_exceed: str = "fail_closed") -> ReasoningPolicy:
    """Build a policy with two operator-aware selection rules."""
    return ReasoningPolicy(
        schema_version="1",
        id="autodev/reasoning-policy-test",
        version="1.0.0",
        host_api=">=2.0 <3.0",
        selection=SelectionSpec(
            default="autodev/reasoning-react",
            rules=(
                SelectionRule(when={"task.kind": "code_patch"}, use="autodev/reasoning-reflection"),
                SelectionRule(when={"complexity": ">=high"}, use="autodev/reasoning-plan-execute"),
            ),
        ),
        budget=ReasoningBudgetPolicy(
            tokens=24000, cost_usd=0.75, wall_clock_ms=45000, max_steps=12, on_exceed=on_exceed
        ),
        tracing=TracingSpec(),
    )


def _registry() -> ReasoningStrategyRegistry:
    """Return a registry populated with all built-in strategies."""
    registry = ReasoningStrategyRegistry()
    register_builtin_strategies(registry)
    return registry


def test_selection_default_and_operator_rules() -> None:
    """Selection falls back to default and honors operator-aware rules."""
    policy = _policy_with_rules()
    assert resolve_strategy(policy).strategy_id == "autodev/reasoning-react"
    assert resolve_strategy(policy, context={"task.kind": "code_patch"}).strategy_id == "autodev/reasoning-reflection"
    high = resolve_strategy(policy, context={"complexity": "high"})
    assert high.strategy_id == "autodev/reasoning-plan-execute"
    assert high.source == "policy_rule"
    assert resolve_strategy(policy, context={"complexity": "low"}).strategy_id == "autodev/reasoning-react"


def test_selection_precedence() -> None:
    """Manifest < flow node < selector override the policy rules (reference §8.7)."""
    policy = _policy_with_rules()
    context = {"task.kind": "code_patch"}
    assert resolve_strategy(policy, context=context, manifest_strategy="autodev/reasoning-tot").strategy_id == "autodev/reasoning-tot"
    node = resolve_strategy(
        policy, context=context, manifest_strategy="autodev/reasoning-tot", node_override="autodev/reasoning-native-tools"
    )
    assert node.strategy_id == "autodev/reasoning-native-tools"
    selector = resolve_strategy(
        policy, context=context, node_override="autodev/reasoning-native-tools", selector_choice="autodev/reasoning-react"
    )
    assert selector.strategy_id == "autodev/reasoning-react"
    assert selector.source == "selector"


def test_service_runs_selected_strategy_and_traces_decision() -> None:
    """The service runs the selected strategy and traces the decision."""
    events: list[TraceEvent] = []
    service = ReasoningService(
        _registry(), provider=StubLLMProvider(text="FINAL: ok"), on_event=events.append
    )
    policy = default_reasoning_policy(default_strategy="autodev/reasoning-native-tools")
    run_input = ReasoningInput(
        task="t", messages=(), tools=(), policy=policy, budget=budget_from_policy(policy)
    )
    result = asyncio.run(service.run(run_input))
    assert result.output.stop_reason == "completed"
    assert result.decision.strategy_id == "autodev/reasoning-native-tools"
    assert result.degraded_to is None
    assert any(event.name == "reasoning.selection.decided" for event in events)


def test_fallback_degrades_on_budget_exhausted() -> None:
    """An overrun under a degrade_to policy retries with the fallback strategy."""
    events: list[TraceEvent] = []
    provider = _ScriptedProvider(["ACTION search x"])  # ReAct never emits FINAL
    service = ReasoningService(
        _registry(), provider=provider, tool_impls={"search": lambda args: "y"}, on_event=events.append
    )
    policy = default_reasoning_policy(
        default_strategy="autodev/reasoning-react",
        max_steps=2,
        on_exceed="degrade_to:autodev/reasoning-native-tools",
    )
    run_input = ReasoningInput(
        task="t", messages=(), tools=(ToolSpec("search"),), policy=policy, budget=budget_from_policy(policy)
    )
    result = asyncio.run(service.run(run_input))
    assert result.degraded_to == "autodev/reasoning-native-tools"
    assert result.output.stop_reason == "completed"
    assert any(event.name == "reasoning.selection.degraded" for event in events)


def test_fail_closed_returns_budget_exhausted() -> None:
    """With the default fail_closed policy, an overrun is returned unaltered."""
    provider = _ScriptedProvider(["ACTION search x"])
    service = ReasoningService(_registry(), provider=provider, tool_impls={"search": lambda args: "y"})
    policy = default_reasoning_policy(default_strategy="autodev/reasoning-react", max_steps=2)
    run_input = ReasoningInput(
        task="t", messages=(), tools=(ToolSpec("search"),), policy=policy, budget=budget_from_policy(policy)
    )
    result = asyncio.run(service.run(run_input))
    assert result.output.stop_reason == "budget_exhausted"
    assert result.degraded_to is None


def test_agent_budget_adapter() -> None:
    """The Agent Runtime adapter maps AgentBudgets and builds a ReasoningInput."""
    budgets = AgentBudgets(
        tokens_input=1000, tokens_output=200, cost_usd=0.5, wall_clock_seconds=30, max_steps=8, max_tool_calls=10
    )
    budget = budget_from_agent_budgets(budgets)
    assert budget.tokens == 1200
    assert budget.wall_clock_ms == 30000
    assert budget.max_steps == 8
    assert budget.cost_usd == 0.5

    run_input = reasoning_input_from_agent(
        task="do it", policy=default_reasoning_policy(), budgets=budgets, tools=(ToolSpec("s"),)
    )
    assert run_input.task == "do it"
    assert run_input.budget.tokens == 1200
    assert len(run_input.tools) == 1
