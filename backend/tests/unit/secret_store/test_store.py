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
