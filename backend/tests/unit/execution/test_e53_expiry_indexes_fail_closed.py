"""Expiry, index verification, fail-closed, and tenant isolation (E53-S3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.config.settings import Settings
from backend.events.runtime import reset_event_bus_for_tests
from backend.execution.contracts import ExecutionAction, ExecutionActionType
from backend.execution.decisions import DecisionAlreadyResolvedError, DecisionService
from backend.execution.policy import (
    DecisionStatus,
    PolicyCategory,
    PolicyEffect,
    PolicyMissingError,
    PolicyRule,
    PolicyScopeKind,
    PolicyService,
    PolicyStore,
)


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_event_bus_for_tests()
    yield
    reset_event_bus_for_tests()


def _store(tmp_path: Path) -> PolicyStore:
    return PolicyStore(db_path=tmp_path / "policy.db")


def _action(action_id: str = "a1") -> ExecutionAction:
    return ExecutionAction(
        action_id=action_id,
        type=ExecutionActionType.RUN_COMMAND,
        task_id="task-1",
        step_key="task-1",
        command=["pytest"],
    )


# --------------------------------------------------------------------------- expiry


def test_expired_pending_decision_is_reclaimed_exactly_once_and_never_resurrected(
    tmp_path: Path,
) -> None:
    """A timed-out decision cannot later be approved -- expiry sticks (E53-S3-T1)."""
    store = _store(tmp_path)
    service = DecisionService(store=store)
    pending = service.request(
        tenant_id="acme",
        run_id="run-1",
        task_id="task-1",
        action=_action(),
        category=PolicyCategory.SHELL,
        prompt="run pytest?",
    )

    far_future = "2999-01-01T00:00:00+00:00"
    first_sweep = service.expire_due(at=far_future)
    assert len(first_sweep) == 1
    assert first_sweep[0].decision_id == pending.decision_id
    assert first_sweep[0].status is DecisionStatus.TIMED_OUT

    # Sweeping again must not re-expire (nothing left pending) or duplicate the outcome.
    second_sweep = service.expire_due(at=far_future)
    assert second_sweep == []

    with pytest.raises(DecisionAlreadyResolvedError):
        service.resolve(pending.decision_id, tenant_id="acme", decision=DecisionStatus.APPROVED, actor="tester")

    final = store.get_pending_decision(pending.decision_id, tenant_id="acme")
    assert final is not None
    assert final.status is DecisionStatus.TIMED_OUT, "an expired decision never resurrects as pending or approved"


# ----------------------------------------------------------------- index verification


def test_pending_decision_queries_use_the_tenant_scoped_indexes(tmp_path: Path) -> None:
    """The pending/expiry query paths hit an index, not a table scan (E53-S3-T2)."""
    store = _store(tmp_path)
    # Force the migration (and its indexes) to exist against a real SQLite file.
    conn = store._connect()  # noqa: SLF001 - white-box index verification

    def _plan(sql: str, params: tuple[Any, ...]) -> str:
        rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
        return " | ".join(str(tuple(row)) for row in rows)

    list_pending_plan = _plan(
        "SELECT * FROM pending_action_decisions WHERE tenant_id = ? AND status = ?",
        ("acme", DecisionStatus.PENDING.value),
    )
    assert "idx_pending_action_decisions_tenant_status" in list_pending_plan

    expiry_plan = _plan(
        "SELECT * FROM pending_action_decisions WHERE status = ? AND expires_at <= ?",
        (DecisionStatus.PENDING.value, "2999-01-01T00:00:00+00:00"),
    )
    # The expiry sweep is cross-tenant by design (no tenant_id predicate), so
    # the tenant-first idx_pending_action_decisions_tenant_status index
    # cannot serve it (its leading column is tenant_id) -- measuring this
    # with EXPLAIN QUERY PLAN is what E53-S3-T2 asked for, and it is what
    # motivated adding idx_pending_action_decisions_status_expiry.
    assert "idx_pending_action_decisions_status_expiry" in expiry_plan

    task_lookup_plan = _plan(
        "SELECT * FROM pending_action_decisions WHERE tenant_id = ? AND run_id = ? AND task_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        ("acme", "run-1", "task-1"),
    )
    assert "idx_pending_action_decisions_tenant_run" in task_lookup_plan


def test_pending_decision_indexes_exist_after_migration(tmp_path: Path) -> None:
    """The tenant-first indexes E50-S2/E53-S1 declared are physically present."""
    store = _store(tmp_path)
    conn = store._connect()  # noqa: SLF001 - white-box index verification
    index_names = {
        row[1] for row in conn.execute("PRAGMA index_list(pending_action_decisions)").fetchall()
    }
    assert "idx_pending_action_decisions_tenant_run" in index_names
    assert "idx_pending_action_decisions_tenant_status" in index_names
    assert "idx_pending_action_decisions_status_expiry" in index_names


# ------------------------------------------------------------------------ fail-closed


class _UnreachableStore:
    """A store double whose connection always fails, simulating a backend outage."""

    database_url = "postgresql://unreachable/db"

    def connect(self) -> Any:
        raise ConnectionError("backend unreachable")


def test_policy_evaluation_fails_closed_when_the_store_is_unreachable() -> None:
    """An unreachable store must deny (by raising), never silently allow (E53-S3-T3)."""
    store = PolicyStore(store=_UnreachableStore())
    service = PolicyService(store=store, settings=Settings())

    with pytest.raises(ConnectionError):
        service.evaluate(tenant_id="acme", action=_action(), run_id="run-1")


def test_decision_request_fails_closed_when_the_store_is_unreachable() -> None:
    """Requesting a human decision against an unreachable store raises rather than granting (E53-S3-T3)."""
    store = PolicyStore(store=_UnreachableStore())
    service = DecisionService(store=store)

    with pytest.raises(ConnectionError):
        service.request(
            tenant_id="acme",
            run_id="run-1",
            task_id="task-1",
            action=_action(),
            category=PolicyCategory.SHELL,
            prompt="run pytest?",
        )


# --------------------------------------------------------------- tenant isolation


def test_policy_rules_are_isolated_per_tenant(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add_rule(
        "tenant-a",
        PolicyRule(
            category=PolicyCategory.SHELL,
            effect=PolicyEffect.ALLOW,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id="*",
        ),
    )
    assert store.has_any_rules("tenant-a") is True
    assert store.has_any_rules("tenant-b") is False
    assert store.list_rules("tenant-b") == []


def test_dynamic_permissions_are_isolated_per_tenant(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add_dynamic_permission(
        "tenant-a",
        PolicyRule(
            category=PolicyCategory.SHELL,
            effect=PolicyEffect.ALLOW,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id="*",
        ),
        actor="operator@example.com",
    )
    assert store.list_dynamic_permissions("tenant-a") != []
    assert store.list_dynamic_permissions("tenant-b") == []


def test_pending_decisions_are_isolated_per_tenant(tmp_path: Path) -> None:
    store = _store(tmp_path)
    decision = store.create_pending_decision(
        tenant_id="tenant-a",
        run_id="run-1",
        task_id="task-1",
        action_id="a1",
        category=PolicyCategory.SHELL,
        prompt="run pytest?",
        expires_at="2999-01-01T00:00:00+00:00",
    )
    assert store.get_pending_decision(decision.decision_id, tenant_id="tenant-a") is not None
    assert store.get_pending_decision(decision.decision_id, tenant_id="tenant-b") is None
    assert store.get_decision_for_task("run-1", "task-1", tenant_id="tenant-b") is None
    assert store.list_pending_decisions("tenant-b") == []
    # A different tenant cannot resolve (or observe as resolved) another tenant's decision.
    ok = store.resolve_pending_decision(
        decision.decision_id, status=DecisionStatus.APPROVED, decided_by="intruder", tenant_id="tenant-b"
    )
    assert ok is False
    still_pending = store.get_pending_decision(decision.decision_id, tenant_id="tenant-a")
    assert still_pending is not None
    assert still_pending.status is DecisionStatus.PENDING


def test_policy_decision_audit_rows_are_stamped_with_the_recording_tenant(tmp_path: Path) -> None:
    """The append-only audit trail scopes rows by tenant_id at write time (E53-S3-T3)."""
    store = _store(tmp_path)
    store.record_decision(
        tenant_id="tenant-a",
        run_id="run-1",
        action_id="a1",
        category=PolicyCategory.SHELL,
        allowed=True,
        reason="allow rule for shell",
        actor="tester",
    )
    conn = store._connect()  # noqa: SLF001 - no public read API exists for this audit-only table
    rows = conn.execute(
        "SELECT tenant_id FROM execution_policy_decisions WHERE run_id = ?", ("run-1",)
    ).fetchall()
    assert [row[0] for row in rows] == ["tenant-a"]
    other_tenant_rows = conn.execute(
        "SELECT tenant_id FROM execution_policy_decisions WHERE tenant_id = ?", ("tenant-b",)
    ).fetchall()
    assert other_tenant_rows == []


def test_evaluate_denies_in_production_even_with_another_tenants_rules_stored(tmp_path: Path) -> None:
    """A tenant's rules never leak into another tenant's fail-closed evaluation (E53-S3-T3)."""
    store = _store(tmp_path)
    store.add_rule(
        "tenant-a",
        PolicyRule(
            category=PolicyCategory.SHELL,
            effect=PolicyEffect.ALLOW,
            scope_kind=PolicyScopeKind.PROJECT,
            scope_id="*",
        ),
    )
    service = PolicyService(store=store, settings=Settings.model_construct(autodev_profile="prod"))

    with pytest.raises(PolicyMissingError):
        service.evaluate(tenant_id="tenant-b", action=_action(), run_id="run-1")
