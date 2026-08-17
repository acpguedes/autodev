"""Typed contracts for tenant quotas and run budgets (ADR-019).

Money is always stored and compared as integer micro-USD (1 USD =
1,000,000 micro-USD); floating-point currency never appears in this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, Optional

#: Default warning threshold: 8,000 basis points = 80%.
DEFAULT_WARNING_RATIO_BASIS_POINTS = 8_000

MICROS_PER_USD = 1_000_000


class QuotaResource(StrEnum):
    """Resource dimensions a tenant quota or run budget can limit."""

    CONCURRENT_RUNS = "concurrent_runs"
    STORAGE_BYTES = "storage_bytes"
    MONTHLY_TOKENS = "monthly_tokens"
    MONTHLY_COST = "monthly_cost"
    REQUEST_RATE = "request_rate"
    RUN_TOKENS = "run_tokens"
    RUN_COST = "run_cost"
    RUN_WALL_CLOCK = "run_wall_clock"
    RUN_STEPS = "run_steps"


class QuotaDenialReason(StrEnum):
    """Stable, machine-readable reasons a quota/budget admission was denied."""

    LIMIT_EXCEEDED = "limit_exceeded"
    MISSING_POLICY = "missing_policy"
    UNMETERED_RESULT = "unmetered_result"
    UNKNOWN_MODEL_PRICE = "unknown_model_price"
    LEASE_UNAVAILABLE = "lease_unavailable"


def usd_to_micros(amount: Decimal) -> int:
    """Convert a USD amount to integer micro-USD, rounding to the nearest unit.

    Args:
        amount: Dollar amount as a :class:`~decimal.Decimal`. Callers must
            never pass a ``float`` here; float-to-Decimal conversion can
            already have lost precision before this function runs.

    Returns:
        The amount in whole micro-USD, rounded half-up.
    """
    return int(
        (amount * Decimal(MICROS_PER_USD)).to_integral_value(rounding=ROUND_HALF_UP)
    )


@dataclass(frozen=True, slots=True)
class RunBudgetLimits:
    """One run's resource ceilings.

    Every field is optional; ``None`` means "no explicit limit on this
    dimension from this source" — when used as an override passed to
    :func:`narrow_budget`, that means "inherit the parent's limit unchanged"
    rather than "unbounded", since a child can only narrow a parent.

    Attributes:
        max_tokens: Maximum total LLM tokens (input + output) for the run.
        max_cost_microusd: Maximum total cost, in integer micro-USD.
        max_wall_clock_ms: Maximum wall-clock duration, in milliseconds.
        max_steps: Maximum number of run steps.
    """

    max_tokens: int | None = None
    max_cost_microusd: int | None = None
    max_wall_clock_ms: int | None = None
    max_steps: int | None = None

    def __post_init__(self) -> None:
        """Reject non-positive finite limits.

        Raises:
            ValueError: If any set field is not a positive integer.
        """
        for name, value in (
            ("max_tokens", self.max_tokens),
            ("max_cost_microusd", self.max_cost_microusd),
            ("max_wall_clock_ms", self.max_wall_clock_ms),
            ("max_steps", self.max_steps),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be a positive finite limit, got {value}")


def narrow_budget(parent: RunBudgetLimits, requested: RunBudgetLimits) -> RunBudgetLimits:
    """Return the componentwise tighter of two budgets.

    A caller-supplied (or downstream-component-supplied) budget can only
    narrow an ambient parent budget, never widen it: each field of the
    result is the minimum of the corresponding parent/requested fields,
    treating an unset (``None``) field as "defer to the other side".

    Args:
        parent: The effective ambient budget (e.g. the tenant default, or
            the caller's already-narrowed budget so far).
        requested: A further restriction to apply on top of ``parent``.

    Returns:
        A new :class:`RunBudgetLimits` no looser than either input.
    """

    def _min(a: int | None, b: int | None) -> int | None:
        if a is None:
            return b
        if b is None:
            return a
        return min(a, b)

    return RunBudgetLimits(
        max_tokens=_min(parent.max_tokens, requested.max_tokens),
        max_cost_microusd=_min(parent.max_cost_microusd, requested.max_cost_microusd),
        max_wall_clock_ms=_min(parent.max_wall_clock_ms, requested.max_wall_clock_ms),
        max_steps=_min(parent.max_steps, requested.max_steps),
    )


@dataclass(frozen=True, slots=True)
class TenantQuotaPolicy:
    """Durable per-tenant resource policy (ADR-019).

    Attributes:
        tenant_id: Tenant this policy governs.
        max_concurrent_runs: Maximum runs active at once for this tenant.
        max_storage_bytes: Maximum total artifact bytes stored.
        monthly_token_limit: Maximum LLM tokens consumed per UTC calendar
            month.
        monthly_cost_microusd: Maximum spend per UTC calendar month, in
            integer micro-USD.
        requests_per_second: Maximum API requests per second, per credential.
        default_run_budget: The budget applied to a run when the caller does
            not request a (further-narrowing) budget of its own.
        warning_ratio_basis_points: Usage ratio (out of 10,000) at which one
            durable warning is emitted per resource/window.
        version: Optimistic-concurrency version, incremented on every write.
    """

    tenant_id: str
    max_concurrent_runs: int
    max_storage_bytes: int
    monthly_token_limit: int
    monthly_cost_microusd: int
    requests_per_second: int
    default_run_budget: RunBudgetLimits
    warning_ratio_basis_points: int = DEFAULT_WARNING_RATIO_BASIS_POINTS
    version: int = 1

    def __post_init__(self) -> None:
        """Reject an empty tenant id, non-positive limits, or an invalid ratio.

        Raises:
            ValueError: If any invariant above is violated.
        """
        if not self.tenant_id:
            raise ValueError("tenant_id must be a non-empty string")
        for name, value in (
            ("max_concurrent_runs", self.max_concurrent_runs),
            ("max_storage_bytes", self.max_storage_bytes),
            ("monthly_token_limit", self.monthly_token_limit),
            ("monthly_cost_microusd", self.monthly_cost_microusd),
            ("requests_per_second", self.requests_per_second),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be a positive finite limit, got {value}")
        if not 0 <= self.warning_ratio_basis_points <= 10_000:
            raise ValueError("warning_ratio_basis_points must be within [0, 10000]")
        if self.version <= 0:
            raise ValueError("version must be a positive integer")


@dataclass(frozen=True, slots=True)
class UsageDelta:
    """An incremental usage observation to apply to a tenant or run ledger.

    Attributes:
        tokens: Tokens consumed by this observation.
        cost_microusd: Cost of this observation, in integer micro-USD.
        steps: Steps completed by this observation.
        wall_clock_ms: Wall-clock time attributable to this observation.
    """

    tokens: int = 0
    cost_microusd: int = 0
    steps: int = 0
    wall_clock_ms: int = 0


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    """A point-in-time view of one run budget's limits and consumption.

    Attributes:
        limits: The effective (already-narrowed) budget for this run.
        consumed_tokens: Tokens settled so far.
        consumed_cost_microusd: Cost settled so far, in integer micro-USD.
        consumed_steps: Steps checkpointed so far.
        elapsed_wall_clock_ms: Wall-clock time elapsed so far.
        reserved_tokens: Tokens held by in-flight, unsettled reservations.
        reserved_cost_microusd: Cost held by in-flight, unsettled
            reservations, in integer micro-USD.
    """

    limits: RunBudgetLimits
    consumed_tokens: int
    consumed_cost_microusd: int
    consumed_steps: int
    elapsed_wall_clock_ms: int
    reserved_tokens: int = 0
    reserved_cost_microusd: int = 0

    @property
    def remaining(self) -> RunBudgetLimits:
        """Return the remaining allowance for every limited dimension.

        A dimension with no configured limit remains unset (``None``, i.e.
        unbounded) in the result. Remaining allowance is clamped at zero.
        """

        def _remaining(
            limit: int | None, consumed: int, reserved: int = 0
        ) -> int | None:
            if limit is None:
                return None
            return max(0, limit - consumed - reserved)

        return RunBudgetLimits(
            max_tokens=_remaining(
                self.limits.max_tokens, self.consumed_tokens, self.reserved_tokens
            ),
            max_cost_microusd=_remaining(
                self.limits.max_cost_microusd,
                self.consumed_cost_microusd,
                self.reserved_cost_microusd,
            ),
            max_wall_clock_ms=_remaining(
                self.limits.max_wall_clock_ms, self.elapsed_wall_clock_ms
            ),
            max_steps=_remaining(self.limits.max_steps, self.consumed_steps),
        )


def utc_month_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the half-open ``[start, end)`` of the current UTC calendar month.

    Args:
        now: Instant to compute the window for; defaults to the current
            UTC time.

    Returns:
        A ``(start, end)`` pair of timezone-aware UTC datetimes, where
        ``start`` is midnight on the 1st of the month and ``end`` is
        midnight on the 1st of the following month.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


class QuotaExceededError(Exception):
    """Raised when an admission or accounting operation exceeds a limit.

    Attributes:
        resource: The dimension that was exceeded.
        reason: Stable machine-readable denial reason.
        used: Amount already used/reserved on this dimension.
        limit: The configured limit on this dimension.
    """

    def __init__(
        self,
        *,
        resource: QuotaResource,
        reason: QuotaDenialReason,
        used: int,
        limit: int,
    ) -> None:
        """Build the exception with its structured denial fields.

        Args:
            resource: The dimension that was exceeded.
            reason: Stable machine-readable denial reason.
            used: Amount already used/reserved on this dimension.
            limit: The configured limit on this dimension.
        """
        super().__init__(f"{resource.value} exceeded: {used} >= {limit} ({reason.value})")
        self.resource = resource
        self.reason = reason
        self.used = used
        self.limit = limit


@dataclass(frozen=True, slots=True)
class LeaseResult:
    """Outcome of a run-lease acquisition attempt (store.QuotaStore).

    Attributes:
        granted: Whether the run now holds an active concurrency lease.
        resumed: Whether an existing lease for this exact run was reused
            (idempotent resume) rather than a fresh slot being consumed.
        expires_at: The lease's current expiry, when granted.
    """

    granted: bool
    resumed: bool
    expires_at: Optional[str]


@dataclass(frozen=True, slots=True)
class ReservationResult:
    """Outcome of a storage-byte reservation attempt (store.QuotaStore).

    Attributes:
        granted: Whether the bytes are now held as a reservation.
        reservation_id: The reservation's id (the caller's idempotency key)
            when granted.
    """

    granted: bool
    reservation_id: Optional[str]


@dataclass(frozen=True, slots=True)
class UsageResult:
    """Outcome of recording an incremental monthly usage delta (store.QuotaStore).

    Attributes:
        granted: Whether the delta was recorded (``False`` means the tenant
            was already at or over its limit and nothing was recorded).
        used: Total used after this call (or before, when denied).
        limit: The configured limit this call was checked against.
        crossed_warning: Whether this call is the first to cross the
            configured warning ratio for this tenant/resource/window.
    """

    granted: bool
    used: int
    limit: int
    crossed_warning: bool


def policy_to_json(policy: TenantQuotaPolicy) -> str:
    """Serialize a policy's non-key fields to JSON for durable storage."""
    budget = policy.default_run_budget
    return json.dumps(
        {
            "max_concurrent_runs": policy.max_concurrent_runs,
            "max_storage_bytes": policy.max_storage_bytes,
            "monthly_token_limit": policy.monthly_token_limit,
            "monthly_cost_microusd": policy.monthly_cost_microusd,
            "requests_per_second": policy.requests_per_second,
            "warning_ratio_basis_points": policy.warning_ratio_basis_points,
            "default_run_budget": {
                "max_tokens": budget.max_tokens,
                "max_cost_microusd": budget.max_cost_microusd,
                "max_wall_clock_ms": budget.max_wall_clock_ms,
                "max_steps": budget.max_steps,
            },
        }
    )


def policy_from_json(tenant_id: str, payload: str, version: int) -> TenantQuotaPolicy:
    """Deserialize a stored policy JSON payload back into a typed policy.

    Args:
        tenant_id: Tenant the policy belongs to (stored separately as the
            table's primary key, not duplicated inside the JSON payload).
        payload: The JSON payload written by :func:`policy_to_json`.
        version: The row's current optimistic-concurrency version.

    Returns:
        The deserialized policy.
    """
    data: dict[str, Any] = json.loads(payload)
    budget_data = data["default_run_budget"]
    return TenantQuotaPolicy(
        tenant_id=tenant_id,
        max_concurrent_runs=data["max_concurrent_runs"],
        max_storage_bytes=data["max_storage_bytes"],
        monthly_token_limit=data["monthly_token_limit"],
        monthly_cost_microusd=data["monthly_cost_microusd"],
        requests_per_second=data["requests_per_second"],
        default_run_budget=RunBudgetLimits(
            max_tokens=budget_data.get("max_tokens"),
            max_cost_microusd=budget_data.get("max_cost_microusd"),
            max_wall_clock_ms=budget_data.get("max_wall_clock_ms"),
            max_steps=budget_data.get("max_steps"),
        ),
        warning_ratio_basis_points=data["warning_ratio_basis_points"],
        version=version,
    )


__all__ = [
    "DEFAULT_WARNING_RATIO_BASIS_POINTS",
    "MICROS_PER_USD",
    "BudgetSnapshot",
    "LeaseResult",
    "QuotaDenialReason",
    "QuotaExceededError",
    "QuotaResource",
    "ReservationResult",
    "RunBudgetLimits",
    "TenantQuotaPolicy",
    "UsageDelta",
    "UsageResult",
    "narrow_budget",
    "policy_from_json",
    "policy_to_json",
    "usd_to_micros",
    "utc_month_window",
]
