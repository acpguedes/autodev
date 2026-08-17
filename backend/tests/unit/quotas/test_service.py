"""Tests for QuotaService: policy resolution and warning/exceeded eventing."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config.settings import Settings
from backend.events.runtime import get_event_bus, reset_event_bus_for_tests
from backend.quotas.contracts import (
    QuotaExceededError,
    QuotaResource,
    RunBudgetLimits,
    TenantQuotaPolicy,
)
from backend.quotas.service import QuotaPolicyMissingError, QuotaService
from backend.quotas.store import QuotaStore


@pytest.fixture(autouse=True)
def _fresh_event_bus() -> None:
    """Isolate the process-wide Event Bus singleton across tests in this module."""
    reset_event_bus_for_tests()
    yield
    reset_event_bus_for_tests()


def _service(tmp_path: Path, *, profile: str = "local") -> QuotaService:
    """Build a QuotaService over a throwaway store, with the given profile.

    ``Settings.model_construct`` bypasses the cross-field validation that
    would otherwise require a full production infrastructure stack
    (PostgreSQL/Redis/S3) just to exercise ``autodev_profile == "prod"``'s
    quota fail-closed behavior, which is unrelated to what these tests
    check.
    """
    store = QuotaStore(db_path=tmp_path / "quotas.db")
    if profile == "prod":
        settings = Settings.model_construct(autodev_profile="prod")
    else:
        settings = Settings()
    return QuotaService(store=store, settings=settings)


class TestPolicyResolution:
    """Local finite defaults vs. production fail-closed policy resolution."""

    def test_local_mode_falls_back_to_finite_defaults(self, tmp_path: Path) -> None:
        service = _service(tmp_path, profile="local")
        policy = service.resolve_policy("acme")
        assert policy.max_concurrent_runs == 4
        assert policy.max_storage_bytes == 1 * 1024 * 1024 * 1024
        assert policy.default_run_budget.max_tokens == 2_000_000

    def test_production_without_a_stored_policy_fails_closed(self, tmp_path: Path) -> None:
        service = _service(tmp_path, profile="prod")
        with pytest.raises(QuotaPolicyMissingError):
            service.resolve_policy("acme")

    def test_stored_policy_takes_precedence_over_local_defaults(self, tmp_path: Path) -> None:
        service = _service(tmp_path, profile="local")
        stored = service.set_policy(
            TenantQuotaPolicy(
                tenant_id="acme",
                max_concurrent_runs=99,
                max_storage_bytes=1,
                monthly_token_limit=1,
                monthly_cost_microusd=1,
                requests_per_second=1,
                default_run_budget=RunBudgetLimits(),
            )
        )
        resolved = service.resolve_policy("acme")
        assert resolved == stored
        assert resolved.max_concurrent_runs == 99

    def test_production_with_a_stored_policy_resolves_it(self, tmp_path: Path) -> None:
        service = _service(tmp_path, profile="prod")
        service.set_policy(
            TenantQuotaPolicy(
                tenant_id="acme",
                max_concurrent_runs=7,
                max_storage_bytes=1,
                monthly_token_limit=1,
                monthly_cost_microusd=1,
                requests_per_second=1,
                default_run_budget=RunBudgetLimits(),
            )
        )
        resolved = service.resolve_policy("acme")
        assert resolved.max_concurrent_runs == 7


class TestRateLimit:
    """Per-credential request rate limiting using the tenant's policy."""

    def test_within_limit_is_admitted(self, tmp_path: Path) -> None:
        service = _service(tmp_path, profile="local")
        service.check_rate_limit(tenant_id="acme", credential_id="cred-1")

    def test_exceeding_limit_raises(self, tmp_path: Path) -> None:
        service = _service(tmp_path, profile="local")
        service.set_policy(
            TenantQuotaPolicy(
                tenant_id="acme",
                max_concurrent_runs=1,
                max_storage_bytes=1,
                monthly_token_limit=1,
                monthly_cost_microusd=1,
                requests_per_second=1,
                default_run_budget=RunBudgetLimits(),
            )
        )
        service.check_rate_limit(tenant_id="acme", credential_id="cred-1")
        with pytest.raises(QuotaExceededError):
            service.check_rate_limit(tenant_id="acme", credential_id="cred-1")


class TestMonthlyUsageEventing:
    """Warning/exceeded events fire exactly once per crossing."""

    def _policy(self, **overrides: object) -> TenantQuotaPolicy:
        base = dict(
            tenant_id="acme",
            max_concurrent_runs=4,
            max_storage_bytes=1000,
            monthly_token_limit=1000,
            monthly_cost_microusd=1000,
            requests_per_second=10,
            default_run_budget=RunBudgetLimits(),
        )
        base.update(overrides)
        return TenantQuotaPolicy(**base)  # type: ignore[arg-type]

    def test_crossing_warning_emits_one_quota_warning_event(self, tmp_path: Path) -> None:
        service = _service(tmp_path, profile="local")
        service.set_policy(self._policy())

        service.record_monthly_usage(
            tenant_id="acme", resource=QuotaResource.MONTHLY_TOKENS, delta=850
        )

        envelopes = get_event_bus().replay("acme")
        types = [envelope.type for envelope in envelopes]
        assert types.count("quota.warning") == 1
        warning = next(e for e in envelopes if e.type == "quota.warning")
        assert warning.data["resource"] == "monthly_tokens"
        assert warning.data["used"] == 850

    def test_warning_does_not_refire_on_a_later_call_in_the_same_window(
        self, tmp_path: Path
    ) -> None:
        service = _service(tmp_path, profile="local")
        service.set_policy(self._policy())

        service.record_monthly_usage(
            tenant_id="acme", resource=QuotaResource.MONTHLY_TOKENS, delta=850
        )
        service.record_monthly_usage(
            tenant_id="acme", resource=QuotaResource.MONTHLY_TOKENS, delta=10
        )

        envelopes = get_event_bus().replay("acme")
        assert [e.type for e in envelopes].count("quota.warning") == 1

    def test_exceeding_limit_emits_quota_exceeded_and_raises(self, tmp_path: Path) -> None:
        service = _service(tmp_path, profile="local")
        service.set_policy(self._policy())
        service.record_monthly_usage(
            tenant_id="acme", resource=QuotaResource.MONTHLY_TOKENS, delta=900
        )

        with pytest.raises(QuotaExceededError):
            service.record_monthly_usage(
                tenant_id="acme", resource=QuotaResource.MONTHLY_TOKENS, delta=200
            )

        envelopes = get_event_bus().replay("acme")
        exceeded = next(e for e in envelopes if e.type == "quota.exceeded")
        assert exceeded.data["resource"] == "monthly_tokens"
        assert exceeded.data["used"] == 900


class TestUsageSnapshot:
    """Aggregate usage-snapshot assembly."""

    def test_snapshot_reflects_recorded_usage(self, tmp_path: Path) -> None:
        service = _service(tmp_path, profile="local")
        service.set_policy(
            TenantQuotaPolicy(
                tenant_id="acme",
                max_concurrent_runs=4,
                max_storage_bytes=1000,
                monthly_token_limit=1000,
                monthly_cost_microusd=1000,
                requests_per_second=10,
                default_run_budget=RunBudgetLimits(),
            )
        )
        service.record_monthly_usage(
            tenant_id="acme", resource=QuotaResource.MONTHLY_TOKENS, delta=42
        )

        snapshot = service.get_usage("acme")
        assert snapshot.monthly_tokens_used == 42
        assert snapshot.concurrent_runs == 0
        assert snapshot.storage_bytes_used == 0
