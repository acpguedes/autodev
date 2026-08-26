"""Real multi-connection PostgreSQL concurrency proof for EnvironmentStore (E54-S2).

Every test here opens genuinely independent connections against a real
PostgreSQL database (threads racing the same tenant's concurrency ceiling),
so the invariant is shown to come from the database's advisory lock, not
from anything held in one Python process -- the same proof shape
``backend/tests/unit/quotas/test_postgres_concurrency.py`` (E51-S4) and
``backend/tests/unit/secret_store/test_postgres_concurrency.py`` (E52-S2)
established for QuotaStore/SecretStore. Skips automatically unless
``AUTODEV_TEST_POSTGRES_URL`` is set; CI wiring for a real PostgreSQL
service lands in E57.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from backend.environments.store import EnvironmentRecord

_POSTGRES_URL = os.environ.get("AUTODEV_TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_URL, reason="requires AUTODEV_TEST_POSTGRES_URL (a real PostgreSQL, E54)"
)


def _store():
    """Build a fresh :class:`EnvironmentStore` over its own PostgreSQL connection."""
    from backend.environments.store import EnvironmentStore
    from backend.persistence.postgres_adapter import PostgresStore

    return EnvironmentStore(store=PostgresStore(_POSTGRES_URL))


def _tenant() -> str:
    """A fresh, collision-free tenant id for one test's isolated slice of the shared database."""
    return f"e54-concurrency-{uuid.uuid4().hex}"


def _record(tenant_id: str, environment_id: str) -> EnvironmentRecord:
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
        expires_at=(now + timedelta(hours=1)).isoformat(),
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
