"""Tests for E4-S4 reasoning policies: selection, budgets, and fallback.

Covers the story DoD: a policy selects the strategy by context (with operator-
aware rules and the reference §8.7 precedence); overrun triggers the declared
``degrade_to`` fallback; the default fails closed; and the policy decision is
traced. Also checks the Agent Runtime binding adapter.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.agents.manifest import AgentBudgets
from backend.agents.provider import ScriptedLLMProvider, StubLLMProvider
from backend.persistence.database import reset_store_cache
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


@pytest.fixture(autouse=True)
def _isolated_quota_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point ``ReasoningService``'s default ``QuotaService`` at a throwaway DB.

    Without this, every ``ReasoningService()`` built here would silently
    read/write the repo's shared dev ``autodev.db`` (E11-S3). Since E51,
    ``QuotaStore()``'s default path resolves through
    :func:`backend.persistence.database.get_store`, a process-wide
    ``lru_cache`` -- reset it around the test too, or every test after the
    first would keep reusing the *first* test's throwaway DB regardless of
    this fixture's fresh ``DATABASE_URL``.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'quotas.db'}")
    reset_store_cache()
    yield
    reset_store_cache()


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
    provider = ScriptedLLMProvider(["ACTION search x"])  # ReAct never emits FINAL
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
    provider = ScriptedLLMProvider(["ACTION search x"])
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


class TestTenantBudgetEnforcement:
    """E11-S3/ADR-019: the tenant's default run budget narrows every run."""

    def test_a_tighter_tenant_budget_exhausts_before_the_policys_own_ceiling(self) -> None:
        from backend.quotas.contracts import RunBudgetLimits, TenantQuotaPolicy
        from backend.quotas.service import QuotaService

        # ReAct never emits FINAL here, so the run only stops on a budget.
        provider = ScriptedLLMProvider(["ACTION search x", "ACTION search x", "ACTION search x"])
        quota_service = QuotaService()
        quota_service.set_policy(
            TenantQuotaPolicy(
                tenant_id="local",
                max_concurrent_runs=5,
                max_storage_bytes=1_000_000,
                monthly_token_limit=1_000_000,
                monthly_cost_microusd=1_000_000,
                requests_per_second=10,
                default_run_budget=RunBudgetLimits(max_steps=1),
            )
        )
        service = ReasoningService(
            _registry(),
            provider=provider,
            tool_impls={"search": lambda args: "y"},
            quota_service=quota_service,
        )
        # The policy's own ceiling would allow 10 steps -- only the tenant's
        # narrower max_steps=1 should be what actually stops this run.
        policy = default_reasoning_policy(default_strategy="autodev/reasoning-react", max_steps=10)
        run_input = ReasoningInput(
            task="t", messages=(), tools=(ToolSpec("search"),), policy=policy, budget=budget_from_policy(policy)
        )
        result = asyncio.run(service.run(run_input))
        assert result.output.stop_reason == "budget_exhausted"
        assert result.output.usage.steps == 1

    def test_a_completed_run_records_monthly_token_and_cost_usage(self) -> None:
        from backend.quotas.contracts import RunBudgetLimits, TenantQuotaPolicy
        from backend.quotas.service import QuotaService

        quota_service = QuotaService()
        quota_service.set_policy(
            TenantQuotaPolicy(
                tenant_id="local",
                max_concurrent_runs=5,
                max_storage_bytes=1_000_000,
                monthly_token_limit=1_000_000,
                monthly_cost_microusd=1_000_000,
                requests_per_second=10,
                default_run_budget=RunBudgetLimits(),
            )
        )
        service = ReasoningService(
            _registry(),
            provider=StubLLMProvider(text="FINAL: ok", tokens_input=50, tokens_output=10, cost_usd=0.01),
            quota_service=quota_service,
        )
        policy = default_reasoning_policy(default_strategy="autodev/reasoning-native-tools")
        run_input = ReasoningInput(
            task="t", messages=(), tools=(), policy=policy, budget=budget_from_policy(policy)
        )
        result = asyncio.run(service.run(run_input))
        assert result.output.stop_reason == "completed"
        assert result.output.usage.tokens == 60

        usage = quota_service.get_usage("local")
        assert usage.monthly_tokens_used == 60
        assert usage.monthly_cost_microusd_used == 10_000

    def test_monthly_overrun_does_not_corrupt_an_already_completed_run(self) -> None:
        """A post-hoc bookkeeping denial must never turn a real result into a failure."""
        from backend.quotas.contracts import RunBudgetLimits, TenantQuotaPolicy
        from backend.quotas.service import QuotaService

        quota_service = QuotaService()
        quota_service.set_policy(
            TenantQuotaPolicy(
                tenant_id="local",
                max_concurrent_runs=5,
                max_storage_bytes=1_000_000,
                # Below whatever tiny token usage a single stub completion
                # produces, so record_monthly_usage is guaranteed to deny.
                monthly_token_limit=1,
                monthly_cost_microusd=1_000_000,
                requests_per_second=10,
                default_run_budget=RunBudgetLimits(),
            )
        )
        service = ReasoningService(
            _registry(),
            provider=StubLLMProvider(text="FINAL: ok", tokens_input=50, tokens_output=10),
            quota_service=quota_service,
        )
        policy = default_reasoning_policy(default_strategy="autodev/reasoning-native-tools")
        run_input = ReasoningInput(
            task="t", messages=(), tools=(), policy=policy, budget=budget_from_policy(policy)
        )
        result = asyncio.run(service.run(run_input))
        # The engine already completed the run and returned real usage; the
        # subsequent monthly-limit denial (60 tokens > limit of 1) must not
        # retroactively turn this into a failure.
        assert result.output.stop_reason == "completed"
        assert result.output.usage.tokens == 60
