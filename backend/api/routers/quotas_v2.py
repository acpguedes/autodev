"""v2 Control Plane API — tenant quota policy and usage (E11-S3, ADR-019)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.api.authorization import requires_scope
from backend.api.rbac_v2 import PrincipalV2, require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2, v2_error
from backend.quotas.contracts import RunBudgetLimits, TenantQuotaPolicy
from backend.quotas.service import QuotaService, TenantUsageSnapshot

router = APIRouter(prefix="/v2/quotas", tags=["quotas"], dependencies=[Depends(require_v2_principal)])


def get_quota_service() -> QuotaService:
    """Build a :class:`QuotaService` bound to the shared durable store.

    Constructed fresh per request, matching every other ``/v2`` router's
    service-provider convention (see ``sessions_v2.get_orchestrator_v2``).

    Returns:
        A new :class:`QuotaService`.
    """
    return QuotaService()


class RunBudgetLimitsV2(BaseModel):
    """One run's resource ceilings, as exposed over the API."""

    model_config = ConfigDict(populate_by_name=True)

    max_tokens: int | None = Field(default=None, alias="maxTokens")
    max_cost_microusd: int | None = Field(default=None, alias="maxCostMicrousd")
    max_wall_clock_ms: int | None = Field(default=None, alias="maxWallClockMs")
    max_steps: int | None = Field(default=None, alias="maxSteps")

    def to_limits(self) -> RunBudgetLimits:
        """Convert this request/response model into its domain type."""
        return RunBudgetLimits(
            max_tokens=self.max_tokens,
            max_cost_microusd=self.max_cost_microusd,
            max_wall_clock_ms=self.max_wall_clock_ms,
            max_steps=self.max_steps,
        )

    @classmethod
    def from_limits(cls, limits: RunBudgetLimits) -> "RunBudgetLimitsV2":
        """Build the API model from a domain :class:`RunBudgetLimits`."""
        return cls(
            maxTokens=limits.max_tokens,
            maxCostMicrousd=limits.max_cost_microusd,
            maxWallClockMs=limits.max_wall_clock_ms,
            maxSteps=limits.max_steps,
        )


class TenantQuotaPolicyV2(BaseModel):
    """A tenant's durable quota policy, as exposed over the API."""

    model_config = ConfigDict(populate_by_name=True)

    max_concurrent_runs: int = Field(alias="maxConcurrentRuns")
    max_storage_bytes: int = Field(alias="maxStorageBytes")
    monthly_token_limit: int = Field(alias="monthlyTokenLimit")
    monthly_cost_microusd: int = Field(alias="monthlyCostMicrousd")
    requests_per_second: int = Field(alias="requestsPerSecond")
    default_run_budget: RunBudgetLimitsV2 = Field(alias="defaultRunBudget")
    warning_ratio_basis_points: int = Field(default=8_000, alias="warningRatioBasisPoints")
    version: int = 1

    @classmethod
    def from_policy(cls, policy: TenantQuotaPolicy) -> "TenantQuotaPolicyV2":
        """Build the API model from a domain :class:`TenantQuotaPolicy`."""
        return cls(
            maxConcurrentRuns=policy.max_concurrent_runs,
            maxStorageBytes=policy.max_storage_bytes,
            monthlyTokenLimit=policy.monthly_token_limit,
            monthlyCostMicrousd=policy.monthly_cost_microusd,
            requestsPerSecond=policy.requests_per_second,
            defaultRunBudget=RunBudgetLimitsV2.from_limits(policy.default_run_budget),
            warningRatioBasisPoints=policy.warning_ratio_basis_points,
            version=policy.version,
        )


class SetTenantQuotaPolicyRequestV2(BaseModel):
    """Request body for ``PUT /v2/quotas/policy``."""

    model_config = ConfigDict(populate_by_name=True)

    max_concurrent_runs: int = Field(alias="maxConcurrentRuns")
    max_storage_bytes: int = Field(alias="maxStorageBytes")
    monthly_token_limit: int = Field(alias="monthlyTokenLimit")
    monthly_cost_microusd: int = Field(alias="monthlyCostMicrousd")
    requests_per_second: int = Field(alias="requestsPerSecond")
    default_run_budget: RunBudgetLimitsV2 = Field(alias="defaultRunBudget")
    warning_ratio_basis_points: int = Field(default=8_000, alias="warningRatioBasisPoints")
    expected_version: int | None = Field(default=None, alias="expectedVersion")


class TenantUsageSnapshotV2(BaseModel):
    """A tenant's current usage against its effective policy."""

    model_config = ConfigDict(populate_by_name=True)

    schemaVersion: str = SCHEMA_VERSION_V2
    policy: TenantQuotaPolicyV2
    concurrent_runs: int = Field(alias="concurrentRuns")
    storage_bytes_used: int = Field(alias="storageBytesUsed")
    monthly_tokens_used: int = Field(alias="monthlyTokensUsed")
    monthly_cost_microusd_used: int = Field(alias="monthlyCostMicrousdUsed")
    month_window_key: str = Field(alias="monthWindowKey")

    @classmethod
    def from_snapshot(cls, snapshot: TenantUsageSnapshot) -> "TenantUsageSnapshotV2":
        """Build the API model from a domain :class:`TenantUsageSnapshot`."""
        return cls(
            policy=TenantQuotaPolicyV2.from_policy(snapshot.policy),
            concurrentRuns=snapshot.concurrent_runs,
            storageBytesUsed=snapshot.storage_bytes_used,
            monthlyTokensUsed=snapshot.monthly_tokens_used,
            monthlyCostMicrousdUsed=snapshot.monthly_cost_microusd_used,
            monthWindowKey=snapshot.month_window_key,
        )


@requires_scope("quota:read")
@router.get("/usage", response_model=TenantUsageSnapshotV2)
def get_tenant_usage_v2(
    quota_service: QuotaService = Depends(get_quota_service),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> TenantUsageSnapshotV2:
    """Return the caller's own tenant's current usage against its policy.

    Args:
        quota_service: Quota service dependency.
        principal: Authenticated caller; its tenant is the only tenant this
            endpoint can ever query — no request parameter selects a
            different one.

    Returns:
        The tenant's usage snapshot.
    """
    return TenantUsageSnapshotV2.from_snapshot(quota_service.get_usage(principal.tenant_id))


@requires_scope("quota:read")
@router.get("/policy", response_model=TenantQuotaPolicyV2)
def get_tenant_policy_v2(
    quota_service: QuotaService = Depends(get_quota_service),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> TenantQuotaPolicyV2:
    """Return the caller's own tenant's effective quota policy.

    Args:
        quota_service: Quota service dependency.
        principal: Authenticated caller; its tenant is the only tenant this
            endpoint can ever query.

    Returns:
        The tenant's effective policy (durably stored, or local defaults).
    """
    return TenantQuotaPolicyV2.from_policy(quota_service.resolve_policy(principal.tenant_id))


@requires_scope("quota:admin")
@router.put("/policy", response_model=TenantQuotaPolicyV2)
def set_tenant_policy_v2(
    request: SetTenantQuotaPolicyRequestV2,
    quota_service: QuotaService = Depends(get_quota_service),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> TenantQuotaPolicyV2:
    """Durably set the caller's own tenant's quota policy.

    Args:
        request: The policy to store, with an optional
            ``expectedVersion`` for optimistic-concurrency control.
        quota_service: Quota service dependency.
        principal: Authenticated caller (must hold ``quota:admin``); its
            tenant is the only tenant this endpoint can ever write.

    Returns:
        The stored policy, with its incremented version.

    Raises:
        HTTPException: 409 if ``expectedVersion`` no longer matches the
            currently stored version (concurrent write).
    """
    policy = TenantQuotaPolicy(
        tenant_id=principal.tenant_id,
        max_concurrent_runs=request.max_concurrent_runs,
        max_storage_bytes=request.max_storage_bytes,
        monthly_token_limit=request.monthly_token_limit,
        monthly_cost_microusd=request.monthly_cost_microusd,
        requests_per_second=request.requests_per_second,
        default_run_budget=request.default_run_budget.to_limits(),
        warning_ratio_basis_points=request.warning_ratio_basis_points,
    )
    try:
        stored = quota_service.set_policy(policy, expected_version=request.expected_version)
    except ValueError as exc:
        v2_error(409, str(exc))
    return TenantQuotaPolicyV2.from_policy(stored)


__all__ = [
    "RunBudgetLimitsV2",
    "SetTenantQuotaPolicyRequestV2",
    "TenantQuotaPolicyV2",
    "TenantUsageSnapshotV2",
    "get_quota_service",
    "get_tenant_policy_v2",
    "get_tenant_usage_v2",
    "router",
    "set_tenant_policy_v2",
]
