"""Tests for narrowing a Reasoning Engine ``Budget`` by a tenant run budget."""

from __future__ import annotations

from backend.quotas.contracts import RunBudgetLimits
from backend.quotas.reasoning_budget import narrow_reasoning_budget
from backend.reasoning.contract import Budget

_REQUESTED = Budget(tokens=1_000, cost_usd=2.0, wall_clock_ms=60_000, max_steps=20)


def test_no_tenant_limits_leaves_the_requested_budget_unchanged() -> None:
    narrowed = narrow_reasoning_budget(RunBudgetLimits(), _REQUESTED)
    assert narrowed == _REQUESTED


def test_a_tighter_tenant_field_wins() -> None:
    tenant = RunBudgetLimits(max_tokens=100)
    narrowed = narrow_reasoning_budget(tenant, _REQUESTED)
    assert narrowed.tokens == 100
    assert narrowed.cost_usd == _REQUESTED.cost_usd
    assert narrowed.wall_clock_ms == _REQUESTED.wall_clock_ms
    assert narrowed.max_steps == _REQUESTED.max_steps


def test_a_looser_tenant_field_never_widens_the_requested_budget() -> None:
    tenant = RunBudgetLimits(max_tokens=1_000_000)
    narrowed = narrow_reasoning_budget(tenant, _REQUESTED)
    assert narrowed.tokens == _REQUESTED.tokens


def test_cost_micro_usd_converts_exactly_to_float_usd() -> None:
    tenant = RunBudgetLimits(max_cost_microusd=500_000)  # $0.50
    narrowed = narrow_reasoning_budget(tenant, _REQUESTED)
    assert narrowed.cost_usd == 0.5


def test_every_dimension_can_be_narrowed_independently() -> None:
    tenant = RunBudgetLimits(
        max_tokens=10, max_cost_microusd=1_000_000, max_wall_clock_ms=5_000, max_steps=2
    )
    narrowed = narrow_reasoning_budget(tenant, _REQUESTED)
    assert narrowed == Budget(tokens=10, cost_usd=1.0, wall_clock_ms=5_000, max_steps=2)
