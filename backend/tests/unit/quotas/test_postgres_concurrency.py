"""Real multi-connection PostgreSQL concurrency proof for QuotaStore (E51-S2/S3/S4).

Every test here opens genuinely independent connections against a real
PostgreSQL database (threads for same-process concurrency, separate OS
processes for the lease-acquisition cross-process check E51-S4-T2 calls
for, so the invariant is shown to come from the database's row locking, not
from anything held in one Python process). Skips automatically unless
``AUTODEV_TEST_POSTGRES_URL`` is set, mirroring
``backend/tests/unit/persistence/test_backup_restore.py``'s existing
convention -- CI wiring for a real PostgreSQL service lands in E57.

Run ids and idempotency keys are always prefixed with the test's own
(randomly generated) tenant id: ``run_leases``/``storage_reservations`` keys
are global across every tenant, and a shared, persistent local PostgreSQL
(the E57-S1 real-CI-service is not wired up yet -- DoR permits "local
Compose meanwhile") can otherwise carry rows left behind by an earlier,
differently-tenanted test run.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import pytest

_POSTGRES_URL = os.environ.get("AUTODEV_TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_URL, reason="requires AUTODEV_TEST_POSTGRES_URL (a real PostgreSQL, E51)"
)


def _store():
    """Build a fresh :class:`QuotaStore` over its own PostgreSQL connection."""
    from backend.persistence.postgres_adapter import PostgresStore
    from backend.quotas.store import QuotaStore

    return QuotaStore(store=PostgresStore(_POSTGRES_URL))


def _tenant() -> str:
    """A fresh, collision-free tenant id for one test's isolated slice of the shared database."""
    import uuid

    return f"e51-concurrency-{uuid.uuid4().hex}"


def test_concurrent_lease_acquisition_grants_exactly_one() -> None:
    """16 threads race the same tenant's single concurrency slot -- exactly one wins (E51-S2-T2/T3)."""
    tenant_id = _tenant()
    attempts = 16

    def _acquire(index: int) -> bool:
        store = _store()
        result = store.acquire_run_lease(
            tenant_id=tenant_id,
            run_id=f"{tenant_id}-run-{index}",
            max_concurrent_runs=1,
            lease_seconds=90,
        )
        return result.granted

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        outcomes = list(pool.map(_acquire, range(attempts)))

    assert outcomes.count(True) == 1
    assert _store().count_active_leases(tenant_id) == 1


def _acquire_lease_in_subprocess(args: tuple[str, str, str]) -> bool:
    """Worker for :func:`test_lease_acquisition_grants_exactly_one_across_processes`.

    Runs in its own OS process with its own PostgreSQL connection -- proving
    the mutual exclusion is enforced by the database's row lock, not by
    anything shared within one Python process (E51-S4-T2).

    Args:
        args: ``(database_url, tenant_id, run_id)``.

    Returns:
        Whether this process's acquisition attempt was granted.
    """
    database_url, tenant_id, run_id = args
    from backend.persistence.postgres_adapter import PostgresStore
    from backend.quotas.store import QuotaStore

    store = QuotaStore(store=PostgresStore(database_url))
    result = store.acquire_run_lease(
        tenant_id=tenant_id, run_id=run_id, max_concurrent_runs=1, lease_seconds=90
    )
    return result.granted


def test_lease_acquisition_grants_exactly_one_across_processes() -> None:
    """The same race as above, but each attempt is a genuinely separate OS process (E51-S4-T2)."""
    tenant_id = _tenant()
    attempts = 8
    jobs = [(_POSTGRES_URL, tenant_id, f"{tenant_id}-proc-run-{i}") for i in range(attempts)]

    with ProcessPoolExecutor(max_workers=attempts) as pool:
        outcomes = list(pool.map(_acquire_lease_in_subprocess, jobs))

    assert outcomes.count(True) == 1
    assert _store().count_active_leases(tenant_id) == 1


def test_expired_lease_is_reclaimed_by_exactly_one_concurrent_caller() -> None:
    """An expired lease under concurrent reclamation attempts is taken by exactly one caller (E51-S2-T2)."""
    tenant_id = _tenant()
    held_id = f"{tenant_id}-expired-holder"
    setup_store = _store()
    setup_store.acquire_run_lease(
        tenant_id=tenant_id, run_id=held_id, max_concurrent_runs=1, lease_seconds=-1
    )
    assert setup_store.count_active_leases(tenant_id) == 0

    attempts = 12

    def _reclaim(index: int) -> bool:
        store = _store()
        result = store.acquire_run_lease(
            tenant_id=tenant_id,
            run_id=f"{tenant_id}-reclaimer-{index}",
            max_concurrent_runs=1,
            lease_seconds=90,
        )
        return result.granted

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        outcomes = list(pool.map(_reclaim, range(attempts)))

    assert outcomes.count(True) == 1
    assert _store().count_active_leases(tenant_id) == 1
