"""Tenant quota policy resolution and durable warning/exceeded eventing (ADR-019).

:class:`QuotaService` sits between the Control Plane API/CLI and
:class:`~backend.quotas.store.QuotaStore`. It owns exactly two concerns the
store itself does not: resolving *which* policy governs a tenant (an
explicit stored policy in production, finite local defaults otherwise), and
emitting the durable ``quota.warning``/``quota.exceeded`` events the store's
compare-and-set primitives report but never publish themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.config.settings import Settings, get_settings
from backend.events.runtime import emit_event
from backend.quotas.contracts import (
    LeaseResult,
    QuotaDenialReason,
    QuotaExceededError,
    QuotaResource,
    ReservationResult,
    RunBudgetLimits,
    TenantQuotaPolicy,
    utc_month_window,
)
from backend.quotas.store import QuotaStore


class QuotaPolicyMissingError(RuntimeError):
    """Raised in production when a tenant has no durably stored quota policy."""

    def __init__(self, tenant_id: str) -> None:
        """Build the error for a tenant with no configured policy.

        Args:
            tenant_id: Tenant that has no stored policy.
        """
        super().__init__(
            f"tenant {tenant_id!r} has no durable quota policy; production requires "
            "an explicit policy (ADR-019) -- run `autodev quotas set`"
        )
        self.tenant_id = tenant_id


@dataclass(frozen=True, slots=True)
class TenantUsageSnapshot:
    """A tenant's current usage against its policy, across every dimension.

    Attributes:
        policy: The tenant's effective policy.
        concurrent_runs: Currently active (leased) run count.
        storage_bytes_used: Currently held (reserved + committed) bytes.
        monthly_tokens_used: Tokens recorded so far in the current UTC month.
        monthly_cost_microusd_used: Cost recorded so far in the current UTC
            month, in integer micro-USD.
        month_window_key: The UTC month window this snapshot's monthly
            figures are scoped to (``YYYY-MM``).
    """

    policy: TenantQuotaPolicy
    concurrent_runs: int
    storage_bytes_used: int
    monthly_tokens_used: int
    monthly_cost_microusd_used: int
    month_window_key: str


def _month_window_key(settings: Settings) -> str:
    """Return the current UTC month as a stable ``YYYY-MM`` window key."""
    del settings
    start, _end = utc_month_window()
    return start.strftime("%Y-%m")


class QuotaService:
    """Resolves tenant quota policy and durably reports warning/exceeded crossings."""

    def __init__(self, store: Optional[QuotaStore] = None, settings: Optional[Settings] = None) -> None:
        """Build the service over a store and settings snapshot.

        Args:
            store: Durable quota store; defaults to a fresh :class:`QuotaStore`.
            settings: Application settings; defaults to the cached settings.
        """
        self._store = store or QuotaStore()
        self._settings = settings or get_settings()

    def _local_default_policy(self, tenant_id: str) -> TenantQuotaPolicy:
        """Build the finite local-mode default policy from settings (ADR-019)."""
        settings = self._settings
        return TenantQuotaPolicy(
            tenant_id=tenant_id,
            max_concurrent_runs=settings.autodev_quota_local_max_concurrent_runs,
            max_storage_bytes=settings.autodev_quota_local_max_storage_bytes,
            monthly_token_limit=settings.autodev_quota_local_monthly_token_limit,
            monthly_cost_microusd=settings.autodev_quota_local_monthly_cost_microusd,
            requests_per_second=settings.autodev_quota_local_requests_per_second,
            default_run_budget=RunBudgetLimits(
                max_tokens=settings.autodev_quota_default_run_max_tokens,
                max_cost_microusd=settings.autodev_quota_default_run_max_cost_microusd,
                max_wall_clock_ms=settings.autodev_quota_default_run_max_wall_clock_ms,
                max_steps=settings.autodev_quota_default_run_max_steps,
            ),
        )

    def resolve_policy(self, tenant_id: str) -> TenantQuotaPolicy:
        """Resolve the effective policy governing a tenant.

        Production (``autodev_profile == "prod"``) requires an explicit,
        durably stored policy and fails closed without one. Local mode
        falls back to the finite defaults in :meth:`_local_default_policy`.

        Args:
            tenant_id: Tenant to resolve a policy for.

        Returns:
            The tenant's effective policy.

        Raises:
            QuotaPolicyMissingError: In production, when no stored policy
                exists for ``tenant_id``.
        """
        stored = self._store.get_policy(tenant_id)
        if stored is not None:
            return stored
        if self._settings.autodev_profile == "prod" and self._settings.autodev_quota_production_requires_policy:
            raise QuotaPolicyMissingError(tenant_id)
        return self._local_default_policy(tenant_id)

    def set_policy(
        self, policy: TenantQuotaPolicy, *, expected_version: Optional[int] = None
    ) -> TenantQuotaPolicy:
        """Durably store a tenant's policy (owner/admin operation).

        Args:
            policy: The policy to store.
            expected_version: Optimistic-concurrency guard; see
                :meth:`~backend.quotas.store.QuotaStore.upsert_policy`.

        Returns:
            The stored policy, with its incremented version.
        """
        return self._store.upsert_policy(policy, expected_version=expected_version)

    def get_usage(self, tenant_id: str) -> TenantUsageSnapshot:
        """Return a tenant's current usage against its effective policy.

        Args:
            tenant_id: Tenant to snapshot usage for.

        Returns:
            The usage snapshot.
        """
        policy = self.resolve_policy(tenant_id)
        window_key = _month_window_key(self._settings)
        return TenantUsageSnapshot(
            policy=policy,
            concurrent_runs=self._store.count_active_leases(tenant_id),
            storage_bytes_used=self._store.storage_used(tenant_id),
            monthly_tokens_used=self._store.usage_snapshot(
                tenant_id, QuotaResource.MONTHLY_TOKENS.value, window_key
            ),
            monthly_cost_microusd_used=self._store.usage_snapshot(
                tenant_id, QuotaResource.MONTHLY_COST.value, window_key
            ),
            month_window_key=window_key,
        )

    def check_rate_limit(self, *, tenant_id: str, credential_id: str) -> None:
        """Enforce a credential's per-second request rate against its tenant's policy.

        Args:
            tenant_id: Tenant the credential authenticates into.
            credential_id: Stable identifier of the presented credential.

        Raises:
            QuotaExceededError: If the credential's current one-second
                window is already at its limit.
        """
        policy = self.resolve_policy(tenant_id)
        admitted = self._store.consume_request_slot(
            credential_id=credential_id, requests_per_second=policy.requests_per_second
        )
        if not admitted:
            raise QuotaExceededError(
                resource=QuotaResource.REQUEST_RATE,
                reason=QuotaDenialReason.LIMIT_EXCEEDED,
                used=policy.requests_per_second,
                limit=policy.requests_per_second,
            )

    def record_monthly_usage(
        self, *, tenant_id: str, resource: QuotaResource, delta: int
    ) -> None:
        """Record incremental monthly usage, emitting warning/exceeded events.

        Args:
            tenant_id: Tenant the usage belongs to.
            resource: Either :attr:`QuotaResource.MONTHLY_TOKENS` or
                :attr:`QuotaResource.MONTHLY_COST`.
            delta: Amount to add; must be non-negative.

        Raises:
            QuotaExceededError: If recording would exceed the tenant's
                configured monthly limit for ``resource``. A durable
                ``quota.exceeded`` event is emitted before raising.
        """
        policy = self.resolve_policy(tenant_id)
        limit = (
            policy.monthly_token_limit
            if resource is QuotaResource.MONTHLY_TOKENS
            else policy.monthly_cost_microusd
        )
        window_key = _month_window_key(self._settings)
        result = self._store.record_monthly_usage(
            tenant_id=tenant_id,
            resource=resource.value,
            delta=delta,
            window_key=window_key,
            limit=limit,
            warning_ratio_basis_points=policy.warning_ratio_basis_points,
        )
        if not result.granted:
            emit_event(
                "quota.exceeded",
                tenant_id=tenant_id,
                partition_key=tenant_id,
                data={
                    "resource": resource.value,
                    "used": result.used,
                    "limit": result.limit,
                    "windowKey": window_key,
                },
            )
            raise QuotaExceededError(
                resource=resource, reason=QuotaDenialReason.LIMIT_EXCEEDED,
                used=result.used, limit=limit,
            )
        if result.crossed_warning:
            emit_event(
                "quota.warning",
                tenant_id=tenant_id,
                partition_key=tenant_id,
                data={
                    "resource": resource.value,
                    "used": result.used,
                    "limit": result.limit,
                    "windowKey": window_key,
                },
            )

    def acquire_run_lease(self, *, tenant_id: str, run_id: str) -> LeaseResult:
        """Admit a run against the tenant's concurrent-run ceiling, or deny it.

        Raises ``quota.exceeded`` durably on denial, mirroring
        :meth:`record_monthly_usage`.

        Args:
            tenant_id: Tenant the run belongs to.
            run_id: Identifier of the run requesting admission.

        Returns:
            The acquisition outcome (``granted=False`` on denial).
        """
        policy = self.resolve_policy(tenant_id)
        lease = self._store.acquire_run_lease(
            tenant_id=tenant_id,
            run_id=run_id,
            max_concurrent_runs=policy.max_concurrent_runs,
            lease_seconds=self._settings.autodev_quota_run_lease_seconds,
        )
        if not lease.granted:
            emit_event(
                "quota.exceeded",
                tenant_id=tenant_id,
                partition_key=tenant_id,
                data={
                    "resource": QuotaResource.CONCURRENT_RUNS.value,
                    "used": policy.max_concurrent_runs,
                    "limit": policy.max_concurrent_runs,
                    "windowKey": "",
                },
            )
        return lease

    def release_run_lease(self, run_id: str) -> None:
        """Release a run's concurrency lease, freeing its tenant's slot.

        Safe to call even if no lease was ever granted for ``run_id``.

        Args:
            run_id: Identifier of the run to release.
        """
        self._store.release_run_lease(run_id)

    def reserve_storage(
        self, *, tenant_id: str, bytes_requested: int, idempotency_key: str
    ) -> ReservationResult:
        """Reserve storage bytes against the tenant's storage ceiling, or deny it.

        Raises ``quota.exceeded`` durably on denial, mirroring
        :meth:`record_monthly_usage`.

        Args:
            tenant_id: Tenant the reservation belongs to.
            bytes_requested: Bytes to reserve.
            idempotency_key: Caller-supplied key; a retry with the same key
                returns the original outcome rather than double-reserving.

        Returns:
            The reservation outcome (``granted=False`` on denial).
        """
        policy = self.resolve_policy(tenant_id)
        result = self._store.reserve_storage(
            tenant_id=tenant_id,
            bytes_requested=bytes_requested,
            idempotency_key=idempotency_key,
            max_storage_bytes=policy.max_storage_bytes,
        )
        if not result.granted:
            emit_event(
                "quota.exceeded",
                tenant_id=tenant_id,
                partition_key=tenant_id,
                data={
                    "resource": QuotaResource.STORAGE_BYTES.value,
                    "used": policy.max_storage_bytes,
                    "limit": policy.max_storage_bytes,
                    "windowKey": "",
                },
            )
        return result

    def commit_storage_reservation(self, reservation_id: str, *, actual_bytes: int) -> None:
        """Settle a reservation to its actual byte size on a successful write."""
        self._store.commit_storage_reservation(reservation_id, actual_bytes=actual_bytes)

    def release_storage_reservation(self, reservation_id: str) -> None:
        """Release a reservation that will never be committed (failed write)."""
        self._store.release_storage_reservation(reservation_id)


__all__ = ["QuotaPolicyMissingError", "QuotaService", "TenantUsageSnapshot"]
