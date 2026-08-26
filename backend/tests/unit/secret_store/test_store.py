"""Tests for the durable secret-version store (E33-S1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.secret_store.contracts import (
    SecretNotFoundError,
    SecretReference,
    SecretRevokedError,
    SecretStatus,
)
from backend.secret_store.store import SecretStore


def _store(tmp_path: Path) -> SecretStore:
    return SecretStore(db_path=tmp_path / "secrets.db")


def _ref(name: str = "git-token", *, tenant_id: str = "t1", project: str = "default") -> SecretReference:
    return SecretReference(tenant_id=tenant_id, project=project, name=name)


def test_create_and_resolve(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # The store persists whatever ciphertext it is given -- encryption is the
    # service layer's job (backend.secret_store.crypto), not the store's.
    store.create(_ref(), "already-encrypted-blob")
    ciphertext, metadata = store.resolve_latest_active(_ref())
    assert ciphertext == "already-encrypted-blob"
    assert metadata.version == 1
    assert metadata.status is SecretStatus.ACTIVE


def test_create_twice_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_ref(), "v1")
    with pytest.raises(ValueError):
        store.create(_ref(), "v2")


def test_rotate_supersedes_previous_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_ref(), "v1")
    metadata = store.rotate(_ref(), "v2")
    assert metadata.version == 2
    assert metadata.status is SecretStatus.ACTIVE
    ciphertext, resolved = store.resolve_latest_active(_ref())
    assert ciphertext == "v2"
    assert resolved.version == 2


def test_rotate_unknown_secret_raises_not_found(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(SecretNotFoundError):
        store.rotate(_ref(), "v2")


def test_revoke_fails_resolution_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_ref(), "v1")
    store.revoke(_ref())
    with pytest.raises(SecretRevokedError):
        store.resolve_latest_active(_ref())


def test_revoke_unknown_secret_raises_not_found(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(SecretNotFoundError):
        store.revoke(_ref())


def test_resolve_unknown_secret_raises_not_found(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(SecretNotFoundError):
        store.resolve_latest_active(_ref())


def test_tenant_isolation_by_construction(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_ref(tenant_id="t1"), "t1-value")
    with pytest.raises(SecretNotFoundError):
        store.resolve_latest_active(_ref(tenant_id="t2"))


def test_same_name_different_project_never_collides(tmp_path: Path) -> None:
    """E52-S3-T1: same tenant, same secret name, different project -- independent chains."""
    store = _store(tmp_path)
    store.create(_ref(project="p1"), "p1-value")
    store.create(_ref(project="p2"), "p2-value")
    p1_ciphertext, _ = store.resolve_latest_active(_ref(project="p1"))
    p2_ciphertext, _ = store.resolve_latest_active(_ref(project="p2"))
    assert p1_ciphertext == "p1-value"
    assert p2_ciphertext == "p2-value"
    store.rotate(_ref(project="p1"), "p1-value-2")
    p2_after_rotate, _ = store.resolve_latest_active(_ref(project="p2"))
    assert p2_after_rotate == "p2-value", "rotating one project's secret must not affect another's"


def test_get_metadata_never_carries_a_value(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_ref(), "s3cr3t")
    metadata = store.get_metadata(_ref())
    assert metadata is not None
    assert not hasattr(metadata, "value")
    assert not hasattr(metadata, "ciphertext")


def test_list_metadata_scoped_to_tenant_and_project(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_ref("a", tenant_id="t1", project="p1"), "va")
    store.create(_ref("b", tenant_id="t1", project="p2"), "vb")
    store.create(_ref("c", tenant_id="t2", project="p1"), "vc")

    all_t1 = store.list_metadata("t1")
    assert {m.reference.name for m in all_t1} == {"a", "b"}

    p1_only = store.list_metadata("t1", project="p1")
    assert {m.reference.name for m in p1_only} == {"a"}


def test_list_metadata_shows_latest_version_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_ref(), "v1")
    store.rotate(_ref(), "v2")
    store.rotate(_ref(), "v3")
    listed = store.list_metadata("t1")
    assert len(listed) == 1
    assert listed[0].version == 3


def test_same_secret_name_in_different_tenants_never_collides(tmp_path: Path) -> None:
    """E52-S3-T1: same (project, name) in two tenants stores and resolves independently."""
    store = _store(tmp_path)
    store.create(_ref(tenant_id="t1"), "t1-value")
    store.create(_ref(tenant_id="t2"), "t2-value")
    t1_ciphertext, _ = store.resolve_latest_active(_ref(tenant_id="t1"))
    t2_ciphertext, _ = store.resolve_latest_active(_ref(tenant_id="t2"))
    assert t1_ciphertext == "t1-value"
    assert t2_ciphertext == "t2-value"


def test_ciphertext_written_before_the_port_decrypts_unchanged(tmp_path: Path) -> None:
    """E52-S1-T3: a row shaped like the pre-port schema (no rotation_request_id) still resolves."""
    store = _store(tmp_path)
    with store._connect() as conn:  # noqa: SLF001 - simulating a pre-port row directly
        conn.execute(
            "INSERT INTO secrets "
            "(tenant_id, project, name, version, ciphertext, status, backend_kind, "
            " created_at, rotated_at, revoked_at) "
            "VALUES ('t1', 'default', 'legacy-secret', 1, 'legacy-ciphertext', 'active', "
            " 'encrypted_database', '2026-01-01T00:00:00+00:00', NULL, NULL)"
        )
        conn.commit()
    ciphertext, metadata = store.resolve_latest_active(_ref("legacy-secret"))
    assert ciphertext == "legacy-ciphertext"
    assert metadata.version == 1


def test_rotate_with_idempotency_key_retry_creates_no_extra_version(tmp_path: Path) -> None:
    """E52-S2-T3: a retried rotation with the same idempotency key is a no-op."""
    store = _store(tmp_path)
    store.create(_ref(), "v1")
    first = store.rotate(_ref(), "v2", idempotency_key="req-1")
    second = store.rotate(_ref(), "v2-retry-payload", idempotency_key="req-1")
    assert first.version == second.version == 2
    ciphertext, _ = store.resolve_latest_active(_ref())
    assert ciphertext == "v2"
    assert len(store.list_metadata("t1")) == 1


def test_rotate_without_idempotency_key_always_creates_a_new_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_ref(), "v1")
    store.rotate(_ref(), "v2")
    third = store.rotate(_ref(), "v3")
    assert third.version == 3


def test_database_rejects_a_second_active_version_bypassing_the_store(tmp_path: Path) -> None:
    """E52-S2-T2: the one-active-version invariant is enforced by a constraint, not only app logic."""
    import sqlite3

    store = _store(tmp_path)
    store.create(_ref(), "v1")
    with pytest.raises(sqlite3.IntegrityError):
        with store._connect() as conn:  # noqa: SLF001 - deliberately bypassing SecretStore.rotate()
            conn.execute(
                "INSERT INTO secrets "
                "(tenant_id, project, name, version, ciphertext, status, backend_kind, created_at) "
                "VALUES ('t1', 'default', 'git-token', 2, 'v2', 'active', 'encrypted_database', 'now')"
            )
            conn.commit()
