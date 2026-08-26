"""Concurrency contract cases (E56-S3-T1): invariants held identically on both backends.

Generalizes the invariants already proven real-PostgreSQL-only by
``backend/tests/unit/{quotas,execution}/test_postgres_concurrency.py`` so
the same assertion also runs against SQLite. SQLite serializes writers
through a whole-database exclusive lock (``BEGIN IMMEDIATE``, see
``backend/persistence/contract.py::begin_write``) rather than PostgreSQL's
per-row locking -- a different mechanism, but the same observable
invariant: races settle instead of corrupting state, so plain thread-count
assertions (never timing) apply unmodified to both.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from backend.execution.policy import PolicyCategory, PolicyEffect, PolicyRule, PolicyScopeKind
from backend.quotas.contracts import RunBudgetLimits, TenantQuotaPolicy

ATTEMPTS = 8


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def test_concurrent_lease_acquisition_grants_exactly_one(quota_store) -> None:
    tenant_id = _uid("tenant")

    def _acquire(index: int) -> bool:
        return quota_store.acquire_run_lease(
            tenant_id=tenant_id,
            run_id=f"{tenant_id}-run-{index}",
            max_concurrent_runs=1,
            lease_seconds=90,
        ).granted

    with ThreadPoolExecutor(max_workers=ATTEMPTS) as pool:
        outcomes = list(pool.map(_acquire, range(ATTEMPTS)))

    assert outcomes.count(True) == 1
    assert quota_store.count_active_leases(tenant_id) == 1


def test_concurrent_usage_accounting_never_exceeds_the_limit(quota_store) -> None:
    tenant_id = _uid("tenant")
    limit = 5

    def _consume(_: int) -> bool:
        return quota_store.record_monthly_usage(
            tenant_id=tenant_id,
            resource="monthly_tokens",
            delta=1,
            window_key="concurrency-contract",
            limit=limit,
            warning_ratio_basis_points=8_000,
        ).granted

    with ThreadPoolExecutor(max_workers=ATTEMPTS * 2) as pool:
        outcomes = list(pool.map(_consume, range(ATTEMPTS * 2)))

    final_used = quota_store.usage_snapshot(tenant_id, "monthly_tokens", "concurrency-contract")
    assert outcomes.count(True) == limit
    assert final_used == limit


def test_upsert_policy_compare_and_swap_admits_exactly_one_writer(quota_store) -> None:
    tenant_id = _uid("tenant")
    base = TenantQuotaPolicy(
        tenant_id=tenant_id,
        max_concurrent_runs=1,
        max_storage_bytes=1000,
        monthly_token_limit=1000,
        monthly_cost_microusd=1000,
        requests_per_second=1,
        default_run_budget=RunBudgetLimits(),
    )
    first = quota_store.upsert_policy(base)
    lock = threading.Lock()
    successes: list[int] = []

    def _swap(index: int) -> None:
        try:
            updated = quota_store.upsert_policy(
                TenantQuotaPolicy(
                    tenant_id=tenant_id,
                    max_concurrent_runs=index + 2,
                    max_storage_bytes=1000,
                    monthly_token_limit=1000,
                    monthly_cost_microusd=1000,
                    requests_per_second=1,
                    default_run_budget=RunBudgetLimits(),
                ),
                expected_version=first.version,
            )
            with lock:
                successes.append(updated.version)
        except ValueError:
            pass

    with ThreadPoolExecutor(max_workers=ATTEMPTS) as pool:
        list(pool.map(_swap, range(ATTEMPTS)))

    assert len(successes) == 1
    final = quota_store.get_policy(tenant_id)
    assert final is not None
    assert final.version == first.version + 1


def test_concurrent_dynamic_permission_grants_all_apply_without_loss(policy_store) -> None:
    """Concurrent inserts (no compare-and-swap here) must all durably land -- no lost writes."""
    tenant_id = _uid("tenant")

    def _grant(index: int) -> str:
        rule = PolicyRule(
            category=PolicyCategory.SHELL,
            effect=PolicyEffect.ALLOW,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id=f"scope-{index}",
        )
        return policy_store.add_dynamic_permission(tenant_id, rule, actor="contract-test")

    with ThreadPoolExecutor(max_workers=ATTEMPTS) as pool:
        rule_ids = list(pool.map(_grant, range(ATTEMPTS)))

    assert len(set(rule_ids)) == ATTEMPTS
    stored = policy_store.list_dynamic_permissions(tenant_id)
    assert len(stored) == ATTEMPTS
