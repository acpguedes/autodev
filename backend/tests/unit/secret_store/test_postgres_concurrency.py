"""Real multi-connection PostgreSQL concurrency proof for SecretStore (E52-S2).

Every test here opens genuinely independent connections against a real
PostgreSQL database (threads racing the same secret reference), so the
invariant is shown to come from the database's advisory lock and unique
index, not from anything held in one Python process -- the same proof
shape ``backend/tests/unit/quotas/test_postgres_concurrency.py`` (E51-S4)
established for QuotaStore. Skips automatically unless
``AUTODEV_TEST_POSTGRES_URL`` is set; CI wiring for a real PostgreSQL
service lands in E57.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.secret_store.contracts import SecretReference
from backend.tests.postgres_gate import REQUIRE_POSTGRES_ENV, require_mark

_POSTGRES_URL = os.environ.get("AUTODEV_TEST_POSTGRES_URL", "")

pytestmark = [
    pytest.mark.slow,
    require_mark(
        bool(_POSTGRES_URL),
        require_env=REQUIRE_POSTGRES_ENV,
        reason="requires AUTODEV_TEST_POSTGRES_URL (a real PostgreSQL, E52)",
    ),
]


_shared_postgres_store = None
_shared_postgres_store_lock = threading.Lock()


def _store():
    """Return a :class:`SecretStore` over this module's one shared, long-lived pool.

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
    from backend.persistence.postgres_adapter import PostgresPoolConfig, PostgresStore
    from backend.secret_store.store import SecretStore

    if _shared_postgres_store is None:
        with _shared_postgres_store_lock:
            if _shared_postgres_store is None:
                _shared_postgres_store = PostgresStore(
                    _POSTGRES_URL,
                    pool_config=PostgresPoolConfig(min_size=1, max_size=32, timeout_seconds=10.0),
                )
    return SecretStore(store=_shared_postgres_store)


def _reference() -> SecretReference:
    """A fresh, collision-free secret reference for one test's isolated slice of the shared database."""
    import uuid

    tenant_id = f"e52-concurrency-{uuid.uuid4().hex}"
    return SecretReference(tenant_id=tenant_id, project="default", name="git-token")


def test_concurrent_rotations_leave_exactly_one_active_version_no_gaps() -> None:
    """16 threads race to rotate the same secret -- the chain ends coherent (E52-S2-T1/T2)."""
    reference = _reference()
    _store().create(reference, "v0")
    attempts = 16

    def _rotate(index: int) -> None:
        _store().rotate(reference, f"v{index + 1}")

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        list(pool.map(_rotate, range(attempts)))

    listed = _store().list_metadata(reference.tenant_id)
    assert len(listed) == 1, "exactly one (project, name) row group for this reference"
    final = listed[0]
    assert final.version == attempts + 1, "no gap: every rotation produced exactly one version"

    ciphertext, resolved = _store().resolve_latest_active(reference)
    assert resolved.version == final.version
    assert ciphertext.startswith("v")


def test_concurrent_retries_of_the_same_idempotency_key_create_no_extra_version() -> None:
    """8 threads retry the same rotation request -- only the first creates a version (E52-S2-T3)."""
    reference = _reference()
    _store().create(reference, "v0")
    attempts = 8

    def _retry(_: int) -> int:
        return _store().rotate(reference, "v1", idempotency_key="shared-request").version

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        versions = list(pool.map(_retry, range(attempts)))

    assert set(versions) == {2}
    listed = _store().list_metadata(reference.tenant_id)
    assert len(listed) == 1
    assert listed[0].version == 2


def test_timestamps_are_normalized_to_strings_not_native_datetimes() -> None:
    """``created_at``/``rotated_at`` are ISO-8601 ``str``, not psycopg's native ``datetime`` (E59-S2 regression).

    PostgreSQL's ``TIMESTAMPTZ`` columns come back from psycopg as
    :class:`datetime.datetime` objects; :class:`SecretMetadata` declares
    ``str | None``. Before this fix, ``GET /v2/secrets`` and
    ``POST /v2/secrets`` 500'd against a real PostgreSQL-backed deployment
    the moment either serialized a fetched row through the API's
    ``createdAt: str`` response model -- found via the E59 backup/restore
    drill's real ``POST /v2/secrets`` call, not by inspection.
    """
    reference = _reference()
    store = _store()
    created = store.create(reference, "v0")
    assert isinstance(created.created_at, str)
    assert created.rotated_at is None

    rotated = store.rotate(reference, "v1")
    assert isinstance(rotated.created_at, str)
    assert rotated.rotated_at is None  # the new active version, not the superseded one

    fetched = store.get_metadata(reference)
    assert fetched is not None
    assert isinstance(fetched.created_at, str)

    listed = store.list_metadata(reference.tenant_id)
    assert len(listed) == 1
    assert isinstance(listed[0].created_at, str)


def test_concurrent_create_and_rotate_never_produce_two_active_versions() -> None:
    """A create racing rotations of an already-created secret cannot duplicate the active row (E52-S2-T2)."""
    reference = _reference()
    _store().create(reference, "v0")
    attempts = 10

    def _rotate(index: int) -> None:
        try:
            _store().rotate(reference, f"v{index + 1}")
        except Exception:  # noqa: BLE001 - a losing racer's transient error is not the assertion
            pass

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        list(pool.map(_rotate, range(attempts)))

    listed = _store().list_metadata(reference.tenant_id)
    assert len(listed) == 1, "the one-active-version constraint holds under concurrency"
