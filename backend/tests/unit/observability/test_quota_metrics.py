"""Tests for the observable per-tenant quota gauges (E11-S3, ADR-019)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.observability.quota_metrics import register_quota_observables
from backend.quotas.contracts import QuotaResource, RunBudgetLimits, TenantQuotaPolicy
from backend.quotas.service import QuotaService
from backend.quotas.store import QuotaStore
from backend.tests.observability_helpers import capture_observability


def _gauge_values(metrics_data: Any, name: str) -> list[tuple[float, dict[str, Any]]]:
    """Extract (value, attributes) pairs for one gauge from a metrics export snapshot."""
    return [
        (point.value, dict(point.attributes or {}))
        for resource in metrics_data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def _policy(tenant_id: str) -> TenantQuotaPolicy:
    return TenantQuotaPolicy(
        tenant_id=tenant_id,
        max_concurrent_runs=5,
        max_storage_bytes=1_000_000,
        monthly_token_limit=1_000_000,
        monthly_cost_microusd=1_000_000,
        requests_per_second=10,
        default_run_budget=RunBudgetLimits(),
    )


def test_no_tenants_configured_reports_no_data_points(tmp_path: Path) -> None:
    """With no tenant policy stored yet, every gauge reports zero data points."""
    quota_service = QuotaService(store=QuotaStore(tmp_path / "quotas.db"))

    with capture_observability() as capture:
        register_quota_observables(
            meter=capture.runtime.meter_provider.get_meter("test.quotas"), quota_service=quota_service
        )
        capture.runtime.force_flush()
        metrics_data = capture.metric_reader.get_metrics_data()

    assert metrics_data is None or _gauge_values(metrics_data, "autodev_quota_concurrent_runs") == []


def test_gauges_report_per_tenant_usage(tmp_path: Path) -> None:
    """Every documented gauge reports one tenant-labeled observation per stored policy."""
    quota_service = QuotaService(store=QuotaStore(tmp_path / "quotas.db"))
    quota_service.set_policy(_policy("tenant-a"))
    quota_service.set_policy(_policy("tenant-b"))

    quota_service.acquire_run_lease(tenant_id="tenant-a", run_id="run-1")
    quota_service.reserve_storage(tenant_id="tenant-a", bytes_requested=500, idempotency_key="obj-1")
    quota_service.record_monthly_usage(
        tenant_id="tenant-a", resource=QuotaResource.MONTHLY_TOKENS, delta=42
    )

    with capture_observability() as capture:
        register_quota_observables(
            meter=capture.runtime.meter_provider.get_meter("test.quotas"), quota_service=quota_service
        )
        capture.runtime.force_flush()
        metrics_data = capture.metric_reader.get_metrics_data()

    assert metrics_data is not None
    concurrent = dict(
        (attrs["tenant_id"], value)
        for value, attrs in _gauge_values(metrics_data, "autodev_quota_concurrent_runs")
    )
    assert concurrent == {"tenant-a": 1.0, "tenant-b": 0.0}

    storage = dict(
        (attrs["tenant_id"], value)
        for value, attrs in _gauge_values(metrics_data, "autodev_quota_storage_bytes_used")
    )
    assert storage == {"tenant-a": 500.0, "tenant-b": 0.0}

    tokens = dict(
        (attrs["tenant_id"], value)
        for value, attrs in _gauge_values(metrics_data, "autodev_quota_monthly_tokens_used")
    )
    assert tokens == {"tenant-a": 42.0, "tenant-b": 0.0}
