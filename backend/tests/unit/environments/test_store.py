"""Tests for the durable environment lifecycle store (E32-S3/S4; E54-S1)."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.environments.store import EnvironmentDecisionRecord, EnvironmentRecord, EnvironmentStore


def _record(env_id: str, *, tenant_id: str = "t1", expires_in_seconds: int = 3600) -> EnvironmentRecord:
    now = datetime.now(timezone.utc)
    return EnvironmentRecord(
        environment_id=env_id,
        run_id="run-1",
        tenant_id=tenant_id,
        backend_kind="hardened_container",
        profile_id="default",
        profile_hash="deadbeef",
        workspace_path="/tmp/ws",
        status="active",
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=expires_in_seconds)).isoformat(),
    )


def test_create_and_get_environment(tmp_path: Path) -> None:
    store = EnvironmentStore(db_path=tmp_path / "env.db")
    store.create_environment(_record("env-1"))
    fetched = store.get("env-1", tenant_id="t1")
    assert fetched is not None
    assert fetched.status == "active"
    assert fetched.tenant_id == "t1"


def test_get_does_not_leak_across_tenants(tmp_path: Path) -> None:
    store = EnvironmentStore(db_path=tmp_path / "env.db")
    store.create_environment(_record("env-1", tenant_id="t1"))
    assert store.get("env-1", tenant_id="t2") is None


def test_count_active_only_counts_active_unexpired(tmp_path: Path) -> None:
    store = EnvironmentStore(db_path=tmp_path / "env.db")
    store.create_environment(_record("env-1"))
    store.create_environment(_record("env-2", expires_in_seconds=-10))
    assert store.count_active("t1") == 1


def test_mark_status_transitions_and_is_reflected(tmp_path: Path) -> None:
    store = EnvironmentStore(db_path=tmp_path / "env.db")
    store.create_environment(_record("env-1"))
    ok = store.mark_status(
        "env-1", tenant_id="t1", status="torn_down", torn_down_at="2026-01-01T00:00:00+00:00"
    )
    assert ok is True
    fetched = store.get("env-1", tenant_id="t1")
    assert fetched is not None
    assert fetched.status == "torn_down"
    assert fetched.torn_down_at == "2026-01-01T00:00:00+00:00"


def test_mark_status_is_idempotent_once_terminal(tmp_path: Path) -> None:
    """E54-S1-T3: a retried teardown does not overwrite an already-recorded terminal state."""
    store = EnvironmentStore(db_path=tmp_path / "env.db")
    store.create_environment(_record("env-1"))
    first = store.mark_status(
        "env-1", tenant_id="t1", status="torn_down", torn_down_at="2026-01-01T00:00:00+00:00"
    )
    assert first is True

    retried = store.mark_status(
        "env-1", tenant_id="t1", status="torn_down", torn_down_at="2026-06-01T00:00:00+00:00"
    )
    assert retried is False

    fetched = store.get("env-1", tenant_id="t1")
    assert fetched is not None
    assert fetched.torn_down_at == "2026-01-01T00:00:00+00:00"


def test_mark_status_does_not_reopen_a_different_terminal_status(tmp_path: Path) -> None:
    """A record already 'orphaned' cannot be flipped to 'torn_down' by a later racing call."""
    store = EnvironmentStore(db_path=tmp_path / "env.db")
    store.create_environment(_record("env-1"))
    store.mark_status("env-1", tenant_id="t1", status="orphaned", torn_down_at="2026-01-01T00:00:00+00:00")

    changed = store.mark_status(
        "env-1", tenant_id="t1", status="torn_down", torn_down_at="2026-06-01T00:00:00+00:00"
    )
    assert changed is False
    assert store.get("env-1", tenant_id="t1").status == "orphaned"  # type: ignore[union-attr]


def test_list_expired_active_finds_only_past_ttl(tmp_path: Path) -> None:
    store = EnvironmentStore(db_path=tmp_path / "env.db")
    store.create_environment(_record("env-fresh", expires_in_seconds=3600))
    store.create_environment(_record("env-stale", expires_in_seconds=-10))
    cutoff = datetime.now(timezone.utc).isoformat()
    expired = store.list_expired_active("t1", before=cutoff)
    assert [r.environment_id for r in expired] == ["env-stale"]


def test_list_for_run_returns_only_that_runs_environments(tmp_path: Path) -> None:
    store = EnvironmentStore(db_path=tmp_path / "env.db")
    store.create_environment(_record("env-1"))
    other = dataclasses.replace(_record("env-2"), run_id="run-2")
    store.create_environment(other)
    records = store.list_for_run("run-1", tenant_id="t1")
    assert [r.environment_id for r in records] == ["env-1"]


def test_create_environment_denies_at_the_concurrency_ceiling(tmp_path: Path) -> None:
    """E54-S2: the count-then-insert admission check happens atomically, in one call."""
    store = EnvironmentStore(db_path=tmp_path / "env.db")
    admitted_first = store.create_environment(_record("env-1"), max_concurrent=1)
    assert admitted_first is True

    admitted_second = store.create_environment(
        dataclasses.replace(_record("env-2"), run_id="run-2"), max_concurrent=1
    )
    assert admitted_second is False
    assert store.get("env-2", tenant_id="t1") is None
    assert store.count_active("t1") == 1


def test_create_environment_ceiling_is_per_tenant(tmp_path: Path) -> None:
    store = EnvironmentStore(db_path=tmp_path / "env.db")
    store.create_environment(_record("env-1", tenant_id="t1"), max_concurrent=1)
    admitted = store.create_environment(_record("env-2", tenant_id="t2"), max_concurrent=1)
    assert admitted is True


def test_record_and_list_decisions(tmp_path: Path) -> None:
    store = EnvironmentStore(db_path=tmp_path / "env.db")
    store.create_environment(_record("env-1"))
    store.record_decision(
        EnvironmentDecisionRecord(
            decision_id="dec-1",
            environment_id="env-1",
            run_id="run-1",
            tenant_id="t1",
            category="filesystem",
            target="../etc/passwd",
            allowed=False,
            reason="escapes workspace",
            decided_at=datetime.now(timezone.utc).isoformat(),
        )
    )
    decisions = store.list_decisions_for_run("run-1", tenant_id="t1")
    assert len(decisions) == 1
    assert decisions[0].allowed is False
    assert decisions[0].category == "filesystem"
