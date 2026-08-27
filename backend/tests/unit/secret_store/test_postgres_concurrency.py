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


def _store():
    """Build a fresh :class:`SecretStore` over its own PostgreSQL connection."""
    from backend.persistence.postgres_adapter import PostgresStore
    from backend.secret_store.store import SecretStore

    return SecretStore(store=PostgresStore(_POSTGRES_URL))


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
