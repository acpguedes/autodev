"""Contracts for tenant quotas and run budgets (ADR-019)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.quotas.contracts import (
    RunBudgetLimits,
    TenantQuotaPolicy,
    narrow_budget,
    usd_to_micros,
    utc_month_window,
)


def test_usd_to_micros_rounds_half_up() -> None:
    """A fractional-cent amount rounds to the nearest whole micro-USD."""
    assert usd_to_micros(Decimal("1.5")) == 1_500_000
    assert usd_to_micros(Decimal("0.0000005")) == 1
    assert usd_to_micros(Decimal("0.00000049")) == 0


def test_child_budget_can_only_narrow_parent() -> None:
    """A caller-supplied budget tightens, never loosens, the ambient one."""
    parent = RunBudgetLimits(
        max_tokens=10_000,
        max_cost_microusd=2_000_000,
        max_wall_clock_ms=600_000,
        max_steps=100,
    )
    assert narrow_budget(
        parent,
        RunBudgetLimits(max_tokens=2_000, max_steps=20),
    ) == RunBudgetLimits(
        max_tokens=2_000,
        max_cost_microusd=2_000_000,
        max_wall_clock_ms=600_000,
        max_steps=20,
    )


def test_narrow_budget_cannot_widen_a_tighter_request() -> None:
    """A requested limit looser than the parent's is clamped to the parent's."""
    parent = RunBudgetLimits(max_tokens=1_000)
    result = narrow_budget(parent, RunBudgetLimits(max_tokens=5_000))
    assert result.max_tokens == 1_000


def test_run_budget_limits_reject_non_positive_values() -> None:
    """Zero or negative limits are invalid; there is no way to express "unlimited" this way."""
    with pytest.raises(ValueError):
        RunBudgetLimits(max_tokens=0)
    with pytest.raises(ValueError):
        RunBudgetLimits(max_steps=-1)


def test_tenant_quota_policy_requires_positive_finite_limits() -> None:
    """Every quota dimension must be a positive integer; there is no "unlimited" value."""
    with pytest.raises(ValueError):
        TenantQuotaPolicy(
            tenant_id="acme",
            max_concurrent_runs=0,
            max_storage_bytes=1,
            monthly_token_limit=1,
            monthly_cost_microusd=1,
            requests_per_second=1,
            default_run_budget=RunBudgetLimits(),
        )


def test_tenant_quota_policy_rejects_empty_tenant_id() -> None:
    """A policy must be bound to a concrete tenant."""
    with pytest.raises(ValueError):
        TenantQuotaPolicy(
            tenant_id="",
            max_concurrent_runs=4,
            max_storage_bytes=1,
            monthly_token_limit=1,
            monthly_cost_microusd=1,
            requests_per_second=1,
            default_run_budget=RunBudgetLimits(),
        )


def test_warning_ratio_basis_points_defaults_to_eighty_percent() -> None:
    """The default warning threshold is exactly 8,000 basis points (80%)."""
    policy = TenantQuotaPolicy(
        tenant_id="acme",
        max_concurrent_runs=4,
        max_storage_bytes=1,
        monthly_token_limit=1,
        monthly_cost_microusd=1,
        requests_per_second=1,
        default_run_budget=RunBudgetLimits(),
    )
    assert policy.warning_ratio_basis_points == 8_000


def test_warning_ratio_basis_points_rejects_out_of_range_values() -> None:
    """A ratio outside [0, 10000] basis points is invalid."""
    with pytest.raises(ValueError):
        TenantQuotaPolicy(
            tenant_id="acme",
            max_concurrent_runs=4,
            max_storage_bytes=1,
            monthly_token_limit=1,
            monthly_cost_microusd=1,
            requests_per_second=1,
            default_run_budget=RunBudgetLimits(),
            warning_ratio_basis_points=10_001,
        )


def test_utc_month_window_spans_exactly_one_calendar_month() -> None:
    """The window covers midnight-to-midnight UTC for the given month, including a year rollover."""
    start, end = utc_month_window(datetime(2026, 8, 15, 12, 30, tzinfo=timezone.utc))
    assert start == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 1, tzinfo=timezone.utc)

    dec_start, dec_end = utc_month_window(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc))
    assert dec_start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert dec_end == datetime(2027, 1, 1, tzinfo=timezone.utc)
