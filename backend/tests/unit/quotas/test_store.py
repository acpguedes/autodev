"""Tests for the durable tenant quota store (ADR-019, E11-S3 Task 3)."""

from __future__ import annotations

import dataclasses
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from backend.quotas.contracts import RunBudgetLimits, TenantQuotaPolicy, usd_to_micros
from backend.quotas.store import QuotaStore


@pytest.fixture()
def store(tmp_path: Path) -> QuotaStore:
    """A fresh :class:`QuotaStore` on a throwaway SQLite database."""
    return QuotaStore(db_path=tmp_path / "quotas.db")


def _policy(tenant_id: str = "acme") -> TenantQuotaPolicy:
    """Build a representative policy for tests."""
    return TenantQuotaPolicy(
        tenant_id=tenant_id,
        max_concurrent_runs=2,
        max_storage_bytes=1000,
        monthly_token_limit=10_000,
        monthly_cost_microusd=usd_to_micros(Decimal("5.00")),
        requests_per_second=5,
        default_run_budget=RunBudgetLimits(max_tokens=2_000_000),
    )


class TestPolicyCompareAndSwap:
    """Policy get/upsert with optimistic concurrency."""

    def test_missing_policy_returns_none(self, store: QuotaStore) -> None:
        assert store.get_policy("acme") is None

    def test_first_upsert_creates_version_one(self, store: QuotaStore) -> None:
        stored = store.upsert_policy(_policy())
        assert stored.version == 1
        assert store.get_policy("acme") == stored

    def test_upsert_with_matching_expected_version_succeeds(self, store: QuotaStore) -> None:
        first = store.upsert_policy(_policy())
        updated = store.upsert_policy(
            dataclasses.replace(_policy(), max_concurrent_runs=9),
            expected_version=first.version,
        )
        assert updated.version == first.version + 1
        assert updated.max_concurrent_runs == 9

    def test_upsert_with_stale_expected_version_is_rejected(self, store: QuotaStore) -> None:
        store.upsert_policy(_policy())
        with pytest.raises(ValueError, match="expected_version"):
            store.upsert_policy(_policy(), expected_version=99)

    def test_two_racing_writers_only_one_wins_the_stale_compare_and_swap(
        self, store: QuotaStore
    ) -> None:
        """A losing writer's stale expected_version is rejected, not silently applied."""
        first = store.upsert_policy(_policy())
        store.upsert_policy(_policy(), expected_version=first.version)  # advances to v2
        with pytest.raises(ValueError, match="expected_version"):
            store.upsert_policy(_policy(), expected_version=first.version)  # stale v1


class TestRunLeaseAtomicity:
    """Concurrency-lease acquire/heartbeat/release."""

    def test_lease_is_granted_under_the_limit(self, store: QuotaStore) -> None:
        result = store.acquire_run_lease(
            tenant_id="acme", run_id="run-1", max_concurrent_runs=2, lease_seconds=90
        )
        assert result.granted is True
        assert result.resumed is False
        assert store.count_active_leases("acme") == 1

    def test_lease_is_denied_at_the_final_slot(self, store: QuotaStore) -> None:
        store.acquire_run_lease(
            tenant_id="acme", run_id="run-1", max_concurrent_runs=1, lease_seconds=90
        )
        result = store.acquire_run_lease(
            tenant_id="acme", run_id="run-2", max_concurrent_runs=1, lease_seconds=90
        )
        assert result.granted is False
        assert store.count_active_leases("acme") == 1

    def test_reacquiring_the_same_run_id_resumes_idempotently(self, store: QuotaStore) -> None:
        store.acquire_run_lease(
            tenant_id="acme", run_id="run-1", max_concurrent_runs=1, lease_seconds=90
        )
        result = store.acquire_run_lease(
            tenant_id="acme", run_id="run-1", max_concurrent_runs=1, lease_seconds=90
        )
        assert result.granted is True
        assert result.resumed is True
        assert store.count_active_leases("acme") == 1

    def test_expired_lease_is_reclaimed_by_a_new_run(self, store: QuotaStore) -> None:
        store.acquire_run_lease(
            tenant_id="acme", run_id="run-1", max_concurrent_runs=1, lease_seconds=-1
        )
        assert store.count_active_leases("acme") == 0
        result = store.acquire_run_lease(
            tenant_id="acme", run_id="run-2", max_concurrent_runs=1, lease_seconds=90
        )
        assert result.granted is True

    def test_heartbeat_extends_an_active_lease(self, store: QuotaStore) -> None:
        store.acquire_run_lease(
            tenant_id="acme", run_id="run-1", max_concurrent_runs=1, lease_seconds=90
        )
        assert store.heartbeat_run_lease("run-1", lease_seconds=90) is True

    def test_heartbeat_on_released_lease_is_a_noop(self, store: QuotaStore) -> None:
        store.acquire_run_lease(
            tenant_id="acme", run_id="run-1", max_concurrent_runs=1, lease_seconds=90
        )
        store.release_run_lease("run-1")
        assert store.heartbeat_run_lease("run-1", lease_seconds=90) is False

    def test_release_frees_the_concurrency_slot(self, store: QuotaStore) -> None:
        store.acquire_run_lease(
            tenant_id="acme", run_id="run-1", max_concurrent_runs=1, lease_seconds=90
        )
        store.release_run_lease("run-1")
        result = store.acquire_run_lease(
            tenant_id="acme", run_id="run-2", max_concurrent_runs=1, lease_seconds=90
        )
        assert result.granted is True

    def test_concurrent_threads_racing_the_final_slot_grant_exactly_one(
        self, tmp_path: Path
    ) -> None:
        """A real multi-threaded race over the last concurrency slot is serialized correctly."""
        db_path = tmp_path / "race.db"
        QuotaStore(db_path=db_path)  # create schema once up front
        results: list[bool] = []
        lock = threading.Lock()

        def attempt(run_id: str) -> None:
            local_store = QuotaStore(db_path=db_path)
            outcome = local_store.acquire_run_lease(
                tenant_id="acme", run_id=run_id, max_concurrent_runs=1, lease_seconds=90
            )
            with lock:
                results.append(outcome.granted)

        threads = [
            threading.Thread(target=attempt, args=(f"run-{i}",)) for i in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results.count(True) == 1


class TestStorageReservation:
    """Reserve-then-settle storage byte accounting."""

    def test_reservation_is_granted_within_the_ceiling(self, store: QuotaStore) -> None:
        result = store.reserve_storage(
            tenant_id="acme", bytes_requested=500, idempotency_key="k1", max_storage_bytes=1000
        )
        assert result.granted is True
        assert store.storage_used("acme") == 500

    def test_reservation_exceeding_the_ceiling_is_denied(self, store: QuotaStore) -> None:
        store.reserve_storage(
            tenant_id="acme", bytes_requested=800, idempotency_key="k1", max_storage_bytes=1000
        )
        result = store.reserve_storage(
            tenant_id="acme", bytes_requested=300, idempotency_key="k2", max_storage_bytes=1000
        )
        assert result.granted is False
        assert store.storage_used("acme") == 800

    def test_retrying_the_same_idempotency_key_does_not_double_reserve(
        self, store: QuotaStore
    ) -> None:
        first = store.reserve_storage(
            tenant_id="acme", bytes_requested=500, idempotency_key="k1", max_storage_bytes=1000
        )
        second = store.reserve_storage(
            tenant_id="acme", bytes_requested=500, idempotency_key="k1", max_storage_bytes=1000
        )
        assert first.granted is True
        assert second == first
        assert store.storage_used("acme") == 500

    def test_commit_settles_to_the_actual_byte_size(self, store: QuotaStore) -> None:
        result = store.reserve_storage(
            tenant_id="acme", bytes_requested=500, idempotency_key="k1", max_storage_bytes=1000
        )
        assert result.reservation_id is not None
        store.commit_storage_reservation(result.reservation_id, actual_bytes=420)
        assert store.storage_used("acme") == 420

    def test_release_frees_a_reservation_that_will_never_be_committed(
        self, store: QuotaStore
    ) -> None:
        result = store.reserve_storage(
            tenant_id="acme", bytes_requested=500, idempotency_key="k1", max_storage_bytes=1000
        )
        assert result.reservation_id is not None
        store.release_storage_reservation(result.reservation_id)
        assert store.storage_used("acme") == 0


class TestRequestRateLimiting:
    """Fixed one-second-window per-credential rate limiting."""

    def test_requests_within_the_limit_are_admitted(self, store: QuotaStore) -> None:
        for _ in range(3):
            assert store.consume_request_slot(credential_id="cred-1", requests_per_second=3) is True

    def test_the_request_exceeding_the_limit_is_denied(self, store: QuotaStore) -> None:
        for _ in range(2):
            store.consume_request_slot(credential_id="cred-1", requests_per_second=2)
        assert store.consume_request_slot(credential_id="cred-1", requests_per_second=2) is False

    def test_different_credentials_have_independent_windows(self, store: QuotaStore) -> None:
        store.consume_request_slot(credential_id="cred-1", requests_per_second=1)
        assert store.consume_request_slot(credential_id="cred-2", requests_per_second=1) is True


class TestMonthlyUsage:
    """Monthly token/cost usage recording, exhaustion, and once-only warnings."""

    def test_usage_within_limit_is_recorded(self, store: QuotaStore) -> None:
        result = store.record_monthly_usage(
            tenant_id="acme",
            resource="monthly_tokens",
            delta=100,
            window_key="2026-08",
            limit=1000,
            warning_ratio_basis_points=8000,
        )
        assert result.granted is True
        assert result.used == 100
        assert store.usage_snapshot("acme", "monthly_tokens", "2026-08") == 100

    def test_usage_exceeding_limit_is_denied_and_not_recorded(self, store: QuotaStore) -> None:
        store.record_monthly_usage(
            tenant_id="acme",
            resource="monthly_tokens",
            delta=900,
            window_key="2026-08",
            limit=1000,
            warning_ratio_basis_points=8000,
        )
        result = store.record_monthly_usage(
            tenant_id="acme",
            resource="monthly_tokens",
            delta=200,
            window_key="2026-08",
            limit=1000,
            warning_ratio_basis_points=8000,
        )
        assert result.granted is False
        assert store.usage_snapshot("acme", "monthly_tokens", "2026-08") == 900

    def test_crossing_the_warning_ratio_fires_exactly_once(self, store: QuotaStore) -> None:
        first = store.record_monthly_usage(
            tenant_id="acme",
            resource="monthly_tokens",
            delta=850,
            window_key="2026-08",
            limit=1000,
            warning_ratio_basis_points=8000,
        )
        second = store.record_monthly_usage(
            tenant_id="acme",
            resource="monthly_tokens",
            delta=10,
            window_key="2026-08",
            limit=1000,
            warning_ratio_basis_points=8000,
        )
        assert first.crossed_warning is True
        assert second.crossed_warning is False

    def test_a_new_window_key_resets_the_counter(self, store: QuotaStore) -> None:
        store.record_monthly_usage(
            tenant_id="acme",
            resource="monthly_tokens",
            delta=900,
            window_key="2026-08",
            limit=1000,
            warning_ratio_basis_points=8000,
        )
        result = store.record_monthly_usage(
            tenant_id="acme",
            resource="monthly_tokens",
            delta=900,
            window_key="2026-09",
            limit=1000,
            warning_ratio_basis_points=8000,
        )
        assert result.granted is True
        assert result.used == 900
