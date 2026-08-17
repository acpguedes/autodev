"""Observable per-tenant quota gauges, registered through the E11-S1 meter (E11-S3, ADR-019).

No parallel metrics registry: these gauges are read on demand from
:class:`~backend.quotas.service.QuotaService` and exported through the same
OpenTelemetry meter every other AutoDev metric uses. Only tenants with a
durably stored policy are observed -- see
:meth:`~backend.quotas.service.QuotaService.list_tenant_ids`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from opentelemetry.metrics import CallbackOptions, Meter, Observation

from backend.quotas.service import QuotaService


def register_quota_observables(*, meter: Meter, quota_service: QuotaService) -> None:
    """Register observable per-tenant quota usage gauges.

    Args:
        meter: Meter supplied by E11-S1.
        quota_service: Source of tenant policy/usage snapshots.
    """

    def usage_value(
        field: str,
    ) -> Callable[[CallbackOptions], Iterable[Observation]]:
        """Build a callback observing one usage field, one observation per tenant.

        Args:
            field: Attribute name on
                :class:`~backend.quotas.service.TenantUsageSnapshot`.

        Returns:
            A callback yielding one tenant-labeled observation per tenant
            with a durably stored policy.
        """

        def observe(_: CallbackOptions) -> Iterable[Observation]:
            observations = []
            for tenant_id in quota_service.list_tenant_ids():
                snapshot = quota_service.get_usage(tenant_id)
                observations.append(
                    Observation(float(getattr(snapshot, field)), {"tenant_id": tenant_id})
                )
            return observations

        return observe

    meter.create_observable_gauge(
        "autodev_quota_concurrent_runs",
        callbacks=[usage_value("concurrent_runs")],
        description="Tenant's currently active (leased) run count",
    )
    meter.create_observable_gauge(
        "autodev_quota_storage_bytes_used",
        callbacks=[usage_value("storage_bytes_used")],
        description="Tenant's currently held (reserved + committed) artifact storage bytes",
        unit="By",
    )
    meter.create_observable_gauge(
        "autodev_quota_monthly_tokens_used",
        callbacks=[usage_value("monthly_tokens_used")],
        description="Tenant's LLM tokens consumed in the current UTC calendar month",
    )
    meter.create_observable_gauge(
        "autodev_quota_monthly_cost_microusd_used",
        callbacks=[usage_value("monthly_cost_microusd_used")],
        description="Tenant's spend in the current UTC calendar month, in integer micro-USD",
    )


__all__ = ["register_quota_observables"]
