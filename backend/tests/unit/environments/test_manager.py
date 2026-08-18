"""Tests for the environment lifecycle manager (E32-S3/S4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.artifacts.pointers import ArtifactPointerStore
from backend.artifacts.store import LocalArtifactStore
from backend.config.settings import Settings
from backend.environments.backends import HardenedContainerBackend, UnavailableBackend
from backend.environments.contracts import (
    EnvironmentBackendError,
    EnvironmentBackendKind,
    EnvironmentProfile,
)
from backend.environments.manager import EnvironmentCapacityExceededError, EnvironmentManager
from backend.environments.store import EnvironmentStore
from backend.events.runtime import get_event_bus, reset_event_bus_for_tests
from backend.execution.contracts import ExecutionResult
from backend.persistence.sqlite_adapter import SQLiteStore
from backend.secret_store.redaction import reset_registry_for_tests as _reset_secret_registry
from backend.secret_store.service import SecretService
from backend.secret_store.store import SecretStore


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_event_bus_for_tests()
    _reset_secret_registry()
    yield
    reset_event_bus_for_tests()
    _reset_secret_registry()


def _manager(
    tmp_path: Path,
    *,
    max_concurrent: int = 4,
    ttl_seconds: int = 3600,
    backend_kind: EnvironmentBackendKind = EnvironmentBackendKind.HARDENED_CONTAINER,
    secret_service: "SecretService | None" = None,
) -> EnvironmentManager:
    store = EnvironmentStore(db_path=tmp_path / "environments.db")
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        autodev_environment_max_concurrent=max_concurrent,
        autodev_environment_ttl_seconds=ttl_seconds,
        storage_backend="local",
        autodev_artifact_dir=str(tmp_path / "artifacts"),
    )
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    pointers = ArtifactPointerStore(store=SQLiteStore(f"sqlite:///{tmp_path / 'pointers.db'}"))
    backend = (
        HardenedContainerBackend()
        if backend_kind is EnvironmentBackendKind.HARDENED_CONTAINER
        else UnavailableBackend()
    )
    return EnvironmentManager(
        store=store,
        settings=settings,
        artifact_store=artifact_store,
        artifact_pointers=pointers,
        backend_override=(backend_kind, backend),
        secret_service=secret_service
        or SecretService(store=SecretStore(db_path=tmp_path / "secrets.db"), settings=settings),
    )


def test_provision_persists_a_record_and_emits_provisioned_event(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))
    assert handle.backend_kind is EnvironmentBackendKind.HARDENED_CONTAINER

    records = manager.list_for_run("run-1")
    assert len(records) == 1
    assert records[0].status == "active"
    assert records[0].profile_hash == handle.profile.content_hash()

    types = [e.type for e in get_event_bus().replay("run-1")]
    assert "environment.instance.provisioned" in types


def test_provision_fails_closed_at_the_concurrency_ceiling(tmp_path: Path) -> None:
    manager = _manager(tmp_path, max_concurrent=1)
    ws = tmp_path / "ws"
    ws.mkdir()
    manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))
    with pytest.raises(EnvironmentCapacityExceededError):
        manager.provision(run_id="run-2", tenant_id="t1", workspace_ref=str(ws))


def test_provision_ceiling_is_per_tenant(tmp_path: Path) -> None:
    manager = _manager(tmp_path, max_concurrent=1)
    ws = tmp_path / "ws"
    ws.mkdir()
    manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))
    # A different tenant is unaffected by t1's ceiling.
    handle = manager.provision(run_id="run-2", tenant_id="t2", workspace_ref=str(ws))
    assert handle.tenant_id == "t2"


def test_provision_with_unavailable_backend_raises_and_persists_nothing(tmp_path: Path) -> None:
    manager = _manager(tmp_path, backend_kind=EnvironmentBackendKind.UNAVAILABLE)
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(EnvironmentBackendError):
        manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))
    assert manager.list_for_run("run-1") == []


def test_evaluate_filesystem_denies_and_audits_traversal(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))

    denial = manager.evaluate_filesystem(handle, path="../../etc/passwd")
    assert denial is not None
    assert denial.category == "filesystem"

    decisions = manager.list_decisions_for_run("run-1")
    assert len(decisions) == 1
    assert decisions[0].allowed is False

    types = [e.type for e in get_event_bus().replay("run-1")]
    assert "environment.access.denied" in types


def test_evaluate_filesystem_allows_and_audits_workspace_path(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))

    denial = manager.evaluate_filesystem(handle, path="notes.md")
    assert denial is None

    decisions = manager.list_decisions_for_run("run-1")
    assert decisions[0].allowed is True


def test_collect_artifacts_persists_only_declared_outputs(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))

    result_with_output = ExecutionResult(
        action_id="a1",
        task_id="t1",
        step_key="s1",
        status="succeeded",
        started_at="x",
        completed_at="y",
        stdout="hello",
        diff="--- a\n+++ b\n",
    )
    result_without_output = ExecutionResult(
        action_id="a2", task_id="t1", step_key="s1", status="succeeded", started_at="x", completed_at="y"
    )
    keys = manager.collect_artifacts(handle, [result_with_output, result_without_output])
    assert keys == [
        f"t1/environments/{handle.environment_id}/a1.log",
        f"t1/environments/{handle.environment_id}/a1.diff",
    ]


def test_teardown_marks_record_torn_down_and_emits_event(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))

    manager.teardown(handle)

    records = manager.list_for_run("run-1")
    assert records[0].status == "torn_down"
    assert records[0].torn_down_at is not None

    types = [e.type for e in get_event_bus().replay("run-1")]
    assert "environment.instance.retired" in types


def test_reap_orphans_tears_down_expired_active_environments(tmp_path: Path) -> None:
    manager = _manager(tmp_path, ttl_seconds=1)
    ws = tmp_path / "ws"
    ws.mkdir()
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))

    from datetime import datetime, timedelta, timezone

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    reaped = manager.reap_orphans(at=future)
    assert reaped == 1
    record = manager.list_for_run("run-1")[0]
    assert record.status == "orphaned"
    assert record.environment_id == handle.environment_id


def test_reap_orphans_frees_capacity_for_new_provisions(tmp_path: Path) -> None:
    manager = _manager(tmp_path, max_concurrent=1, ttl_seconds=1)
    ws = tmp_path / "ws"
    ws.mkdir()
    manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))

    import time

    time.sleep(1.1)
    # The next provision() call opportunistically reaps the expired
    # environment above before checking the ceiling.
    handle2 = manager.provision(run_id="run-2", tenant_id="t1", workspace_ref=str(ws))
    assert handle2.run_id == "run-2"


# ---------------------------------------------------------------------------
# Secret injection & redaction (E33-S2)
# ---------------------------------------------------------------------------


def test_resolve_secrets_for_profile_resolves_allowlisted_names(tmp_path: Path) -> None:
    secret_store = SecretStore(db_path=tmp_path / "secrets.db")
    settings = Settings(_env_file=None, autodev_secret_encryption_key="k")  # type: ignore[call-arg]
    secret_service = SecretService(store=secret_store, settings=settings)
    from backend.secret_store.contracts import SecretReference

    secret_service.create(
        SecretReference(tenant_id="t1", project="default", name="GIT_TOKEN"),
        "s3cr3t-value",
        actor_id="test",
    )
    manager = _manager(tmp_path, secret_service=secret_service)
    ws = tmp_path / "ws"
    ws.mkdir()
    profile = EnvironmentProfile(env_allowlist=("GIT_TOKEN", "UNBACKED_VAR"))
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws), profile=profile)

    extra_env = manager.resolve_secrets_for_profile(handle)

    assert extra_env == {"GIT_TOKEN": "s3cr3t-value"}


def test_resolve_secrets_for_profile_empty_when_no_allowlist(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws))
    assert manager.resolve_secrets_for_profile(handle) == {}


def test_collect_artifacts_redacts_leaked_secret_and_audits(tmp_path: Path) -> None:
    secret_store = SecretStore(db_path=tmp_path / "secrets.db")
    settings = Settings(_env_file=None, autodev_secret_encryption_key="k")  # type: ignore[call-arg]
    secret_service = SecretService(store=secret_store, settings=settings)
    from backend.secret_store.contracts import SecretReference

    secret_service.create(
        SecretReference(tenant_id="t1", project="default", name="GIT_TOKEN"),
        "s3cr3t-value",
        actor_id="test",
    )
    manager = _manager(tmp_path, secret_service=secret_service)
    ws = tmp_path / "ws"
    ws.mkdir()
    profile = EnvironmentProfile(env_allowlist=("GIT_TOKEN",))
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws), profile=profile)
    manager.resolve_secrets_for_profile(handle)

    leaking_result = ExecutionResult(
        action_id="a1",
        task_id="t1",
        step_key="s1",
        status="succeeded",
        started_at="x",
        completed_at="y",
        stdout="the token is s3cr3t-value",
    )
    manager.collect_artifacts(handle, [leaking_result])

    artifact_store = manager._resolve_artifact_store()  # noqa: SLF001
    key = f"t1/environments/{handle.environment_id}/a1.log"
    stored = artifact_store.get_artifact("logs", key)
    assert b"s3cr3t-value" not in stored
    assert b"REDACTED" in stored

    types = [e.type for e in get_event_bus().replay("run-1")]
    assert "secret.leak.suspected" in types


def test_rotated_secret_takes_effect_on_next_provision(tmp_path: Path) -> None:
    """E33-S3-T1: a rotated secret's new value is what the *next* provision resolves."""
    from backend.secret_store.contracts import SecretReference

    secret_store = SecretStore(db_path=tmp_path / "secrets.db")
    settings = Settings(_env_file=None, autodev_secret_encryption_key="k")  # type: ignore[call-arg]
    secret_service = SecretService(store=secret_store, settings=settings)
    reference = SecretReference(tenant_id="t1", project="default", name="GIT_TOKEN")
    secret_service.create(reference, "v1", actor_id="test")

    manager = _manager(tmp_path, secret_service=secret_service)
    ws = tmp_path / "ws"
    ws.mkdir()
    profile = EnvironmentProfile(env_allowlist=("GIT_TOKEN",))
    handle1 = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws), profile=profile)
    assert manager.resolve_secrets_for_profile(handle1) == {"GIT_TOKEN": "v1"}
    manager.teardown(handle1)

    secret_service.rotate(reference, "v2", actor_id="test")

    handle2 = manager.provision(run_id="run-2", tenant_id="t1", workspace_ref=str(ws), profile=profile)
    assert manager.resolve_secrets_for_profile(handle2) == {"GIT_TOKEN": "v2"}


def test_revoked_secret_is_skipped_on_next_provision(tmp_path: Path) -> None:
    """A revoked reference resolves to nothing for injection -- fails closed, not an exception."""
    from backend.secret_store.contracts import SecretReference

    secret_store = SecretStore(db_path=tmp_path / "secrets.db")
    settings = Settings(_env_file=None, autodev_secret_encryption_key="k")  # type: ignore[call-arg]
    secret_service = SecretService(store=secret_store, settings=settings)
    reference = SecretReference(tenant_id="t1", project="default", name="GIT_TOKEN")
    secret_service.create(reference, "v1", actor_id="test")
    secret_service.revoke(reference, actor_id="test")

    manager = _manager(tmp_path, secret_service=secret_service)
    ws = tmp_path / "ws"
    ws.mkdir()
    profile = EnvironmentProfile(env_allowlist=("GIT_TOKEN",))
    handle = manager.provision(run_id="run-1", tenant_id="t1", workspace_ref=str(ws), profile=profile)

    assert manager.resolve_secrets_for_profile(handle) == {}
