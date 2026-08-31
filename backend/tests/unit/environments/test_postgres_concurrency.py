"""Real multi-connection PostgreSQL concurrency proof for EnvironmentStore (E54-S2/S3).

Every test here opens genuinely independent connections against a real
PostgreSQL database (threads for same-process concurrency, a separate OS
process for the crash-recovery check E54-S3-T3 calls for, so the invariant
is shown to come from the database's row semantics, not from anything held
in one Python process) -- the same proof shape
``backend/tests/unit/quotas/test_postgres_concurrency.py`` (E51-S4) and
``backend/tests/unit/secret_store/test_postgres_concurrency.py`` (E52-S2)
established for QuotaStore/SecretStore. Skips automatically unless
``AUTODEV_TEST_POSTGRES_URL`` is set; CI wiring for a real PostgreSQL
service lands in E57.
"""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from backend.environments.store import EnvironmentRecord
from backend.tests.postgres_gate import REQUIRE_POSTGRES_ENV, require_mark

_POSTGRES_URL = os.environ.get("AUTODEV_TEST_POSTGRES_URL", "")

pytestmark = [
    pytest.mark.slow,
    require_mark(
        bool(_POSTGRES_URL),
        require_env=REQUIRE_POSTGRES_ENV,
        reason="requires AUTODEV_TEST_POSTGRES_URL (a real PostgreSQL, E54)",
    ),
]


_shared_postgres_store = None
_shared_postgres_store_lock = threading.Lock()


def _store():
    """Return an :class:`EnvironmentStore` over this module's one shared, long-lived pool.

    A bounded ``psycopg_pool.ConnectionPool`` (E60-S1) is eagerly opened and
    kept alive for the life of a ``PostgresStore``, unlike the bare ad-hoc
    connection this helper used to hand out -- so every call must share one
    ``PostgresStore``/pool instead of leaking a fresh pool's worth of real
    server connections per call. ``max_size`` covers this file's largest
    concurrent scenario with headroom; each thread below still gets its own
    genuinely independent connection from the pool. Double-checked locking
    guards first construction: several test threads can call this
    simultaneously, and two ``PostgresStore()``s racing their own migration
    runs would otherwise duplicate-key on the schema tables.
    """
    global _shared_postgres_store
    from backend.environments.store import EnvironmentStore
    from backend.persistence.postgres_adapter import PostgresPoolConfig, PostgresStore

    if _shared_postgres_store is None:
        with _shared_postgres_store_lock:
            if _shared_postgres_store is None:
                _shared_postgres_store = PostgresStore(
                    _POSTGRES_URL,
                    pool_config=PostgresPoolConfig(min_size=1, max_size=32, timeout_seconds=10.0),
                )
    return EnvironmentStore(store=_shared_postgres_store)


def _tenant() -> str:
    """A fresh, collision-free tenant id for one test's isolated slice of the shared database."""
    return f"e54-concurrency-{uuid.uuid4().hex}"


def _record(
    tenant_id: str, environment_id: str, *, expires_in_seconds: int = 3600
) -> EnvironmentRecord:
    now = datetime.now(timezone.utc)
    return EnvironmentRecord(
        environment_id=environment_id,
        run_id=f"{environment_id}-run",
        tenant_id=tenant_id,
        backend_kind="hardened_container",
        profile_id="default",
        profile_hash="deadbeef",
        workspace_path="/tmp/ws",
        status="active",
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=expires_in_seconds)).isoformat(),
    )


def test_concurrent_creation_never_exceeds_the_tenant_ceiling() -> None:
    """16 threads race to create environments for the same tenant against a limit of 4 (E54-S2-T2/T3)."""
    tenant_id = _tenant()
    attempts = 16
    limit = 4

    def _create(index: int) -> bool:
        store = _store()
        return store.create_environment(
            _record(tenant_id, f"{tenant_id}-env-{index}"), max_concurrent=limit
        )

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        outcomes = list(pool.map(_create, range(attempts)))

    assert outcomes.count(True) == limit
    assert _store().count_active(tenant_id) == limit


def test_concurrent_creation_ceiling_is_isolated_per_tenant() -> None:
    """Two tenants racing their own ceilings never observe each other's counts (E54-S2-T2)."""
    tenant_a = _tenant()
    tenant_b = _tenant()
    attempts_per_tenant = 8
    limit = 3

    def _create(args: tuple[str, int]) -> bool:
        tenant_id, index = args
        store = _store()
        return store.create_environment(
            _record(tenant_id, f"{tenant_id}-env-{index}"), max_concurrent=limit
        )

    jobs = [(tenant_a, i) for i in range(attempts_per_tenant)] + [
        (tenant_b, i) for i in range(attempts_per_tenant)
    ]

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        list(pool.map(_create, jobs))

    assert _store().count_active(tenant_a) == limit
    assert _store().count_active(tenant_b) == limit


def test_concurrent_reaping_claims_each_expired_environment_exactly_once() -> None:
    """N threads race the same expiry sweep -- exactly one claims each row (E54-S3-T1/T2)."""
    tenant_id = _tenant()
    store = _store()
    environment_ids = [f"{tenant_id}-env-{i}" for i in range(5)]
    for environment_id in environment_ids:
        store.create_environment(_record(tenant_id, environment_id, expires_in_seconds=-10))
    cutoff = datetime.now(timezone.utc).isoformat()
    attempts = 12

    def _claim(_: int) -> list[str]:
        return [r.environment_id for r in _store().claim_expired_active(tenant_id, before=cutoff)]

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        results = list(pool.map(_claim, range(attempts)))

    claimed_ids = [env_id for result in results for env_id in result]
    assert sorted(claimed_ids) == sorted(environment_ids), (
        "every expired environment must be claimed by exactly one racer, no double-claims"
    )
    assert _store().count_active(tenant_id) == 0


def _claim_expired_in_subprocess(args: tuple[str, str, str]) -> list[str]:
    """Worker for :func:`test_crash_recovery_a_second_instance_reclaims_an_orphaned_environment`.

    Runs in its own OS process with its own PostgreSQL connection -- proving
    a second replica (not merely a second thread in the same process as the
    one that "crashed") can reclaim an environment orphaned by a dead owner
    (E54-S3-T3).

    Args:
        args: ``(database_url, tenant_id, before)``.

    Returns:
        The environment ids this process's claim attempt won.
    """
    database_url, tenant_id, before = args
    from backend.environments.store import EnvironmentStore
    from backend.persistence.postgres_adapter import PostgresStore

    store = EnvironmentStore(store=PostgresStore(database_url))
    return [r.environment_id for r in store.claim_expired_active(tenant_id, before=before)]


def test_crash_recovery_a_second_instance_reclaims_an_orphaned_environment() -> None:
    """An environment left "active" by a crashed owner is reclaimed by another replica's process.

    Simulates the owning process dying mid-lifecycle by simply never calling
    teardown() -- the durable record is the only trace of the environment,
    exactly as it would be after a real crash. A second, genuinely separate
    OS process then runs the same sweep a healthy replica would run and
    reclaims it, transitioning the row from "active" to "orphaned"
    (E54-S3-T3). ``count_active`` only counts non-expired active rows
    (``backend/tests/unit/environments/test_store.py::
    test_count_active_only_counts_active_unexpired``), so it already reads
    zero for this already-expired record both before and after the claim;
    the claim's proof is the status transition itself, asserted below.
    """
    tenant_id = _tenant()
    store = _store()
    environment_id = f"{tenant_id}-crashed-env"
    store.create_environment(_record(tenant_id, environment_id, expires_in_seconds=-10))
    assert store.count_active(tenant_id) == 0

    before = datetime.now(timezone.utc).isoformat()
    attempts = 8
    jobs = [(_POSTGRES_URL, tenant_id, before) for _ in range(attempts)]

    with ProcessPoolExecutor(max_workers=attempts) as pool:
        outcomes = list(pool.map(_claim_expired_in_subprocess, jobs))

    claimed_ids = [env_id for outcome in outcomes for env_id in outcome]
    assert claimed_ids == [environment_id], "exactly one process reclaims the orphaned environment"
    assert store.count_active(tenant_id) == 0
    record = store.get(environment_id, tenant_id=tenant_id)
    assert record is not None
    assert record.status == "orphaned"
