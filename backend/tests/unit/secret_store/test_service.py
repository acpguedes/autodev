"""Tests for the secret lifecycle service (E33-S1/S3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config.settings import Settings
from backend.events.runtime import get_event_bus, reset_event_bus_for_tests
from backend.secret_store.contracts import SecretNotFoundError, SecretReference, SecretRevokedError
from backend.secret_store.service import SecretService
from backend.secret_store.store import SecretStore


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_event_bus_for_tests()
    yield
    reset_event_bus_for_tests()


def _service(tmp_path: Path) -> SecretService:
    store = SecretStore(db_path=tmp_path / "secrets.db")
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        autodev_secret_encryption_key="test-only-key-material",
    )
    return SecretService(store=store, settings=settings)


def _ref(name: str = "git-token", *, tenant_id: str = "t1") -> SecretReference:
    return SecretReference(tenant_id=tenant_id, project="default", name=name)


def test_create_then_resolve_roundtrips_the_plaintext_value(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create(_ref(), "s3cr3t-value", actor_id="alice")
    handle = service.resolve_for_injection(_ref(), actor_id="env-1")
    assert handle.value == "s3cr3t-value"
    assert handle.metadata.version == 1


def test_create_emits_secret_created_event_without_a_value(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create(_ref(), "s3cr3t-value", actor_id="alice")
    envelopes = get_event_bus().replay("t1")
    created = [e for e in envelopes if e.type == "secret.created"]
    assert len(created) == 1
    assert "s3cr3t-value" not in str(created[0].data)


def test_rotate_invalidates_the_old_value_for_future_resolution(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create(_ref(), "v1", actor_id="alice")
    service.rotate(_ref(), "v2", actor_id="alice")
    handle = service.resolve_for_injection(_ref(), actor_id="env-1")
    assert handle.value == "v2"


def test_revoke_fails_resolution_closed(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create(_ref(), "v1", actor_id="alice")
    service.revoke(_ref(), actor_id="alice")
    with pytest.raises(SecretRevokedError):
        service.resolve_for_injection(_ref(), actor_id="env-1")


def test_rotate_emits_secret_rotated_event_without_a_value(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create(_ref(), "v1", actor_id="alice")
    service.rotate(_ref(), "v2", actor_id="alice")
    envelopes = get_event_bus().replay("t1")
    rotated = [e for e in envelopes if e.type == "secret.rotated"]
    assert len(rotated) == 1
    assert rotated[0].data["version"] == 2
    assert "v2" not in str(rotated[0].data)


def test_revoke_emits_secret_revoked_event_without_a_value(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create(_ref(), "v1", actor_id="alice")
    service.revoke(_ref(), actor_id="alice")
    envelopes = get_event_bus().replay("t1")
    revoked = [e for e in envelopes if e.type == "secret.revoked"]
    assert len(revoked) == 1
    assert revoked[0].data["actorId"] == "alice"


def test_resolve_emits_secret_resolved_event(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create(_ref(), "v1", actor_id="alice")
    service.resolve_for_injection(_ref(), actor_id="env-1")
    envelopes = get_event_bus().replay("t1")
    resolved = [e for e in envelopes if e.type == "secret.resolved"]
    assert len(resolved) == 1
    assert resolved[0].data["actorId"] == "env-1"
    assert "s3cr3t-value-in-resolve" not in str(resolved[0].data)


def test_resolve_never_leaks_the_plaintext_value_into_the_audit_event(tmp_path: Path) -> None:
    """E52-S3-T2: no audit record, of any secret operation, carries the plaintext value."""
    service = _service(tmp_path)
    service.create(_ref(), "s3cr3t-value-in-resolve", actor_id="alice")
    service.rotate(_ref(), "s3cr3t-value-rotated", actor_id="alice")
    service.resolve_for_injection(_ref(), actor_id="env-1")
    service.revoke(_ref(), actor_id="alice")
    envelopes = get_event_bus().replay("t1")
    for envelope in envelopes:
        assert "s3cr3t-value-in-resolve" not in str(envelope.data)
        assert "s3cr3t-value-rotated" not in str(envelope.data)


class _UnreachableStore:
    """A store double whose connection always fails, simulating a down backend (E52-S3-T3)."""

    def connect(self):  # noqa: ANN201 - test double
        raise ConnectionError("backend unavailable")


def test_resolve_fails_closed_when_the_backend_is_unreachable() -> None:
    """E52-S3-T3: an unreachable store must deny resolution, never fall back to empty."""
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        autodev_secret_encryption_key="test-only-key-material",
    )
    service = SecretService(store=SecretStore(store=_UnreachableStore()), settings=settings)
    with pytest.raises(ConnectionError):
        service.resolve_for_injection(_ref(), actor_id="env-1")


def test_get_metadata_never_carries_a_value(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create(_ref(), "v1", actor_id="alice")
    metadata = service.get_metadata(_ref())
    assert metadata is not None
    assert not hasattr(metadata, "value")


def test_resolve_unknown_secret_raises_not_found(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(SecretNotFoundError):
        service.resolve_for_injection(_ref(), actor_id="env-1")
