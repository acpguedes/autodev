"""Tests for U9 plan store (backend/plans/).

Assertions:
- upsert -> get round-trip returns the correct steps and draft status.
- approve() transitions status to approved and appends an ApprovalRecord.
- reject() transitions status to rejected and appends an ApprovalRecord.
- list_plans() returns all upserted plans.
- get_plan() returns None for an unknown session.
- Table creation is idempotent (calling PlanStore twice on the same path is safe).
"""

from __future__ import annotations

import pytest

from backend.plans.models import ApprovalRecord, PlanDocument, PlanStatus
from backend.plans.store import PlanStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    """A fresh PlanStore backed by a temp sqlite file."""
    db_path = tmp_path / "test_plans.db"
    return PlanStore(db_path=db_path)


# ---------------------------------------------------------------------------
# upsert / get round-trip
# ---------------------------------------------------------------------------


def test_upsert_and_get_round_trip(store: PlanStore) -> None:
    steps = ["Step 1: analyse", "Step 2: implement", "Step 3: test"]
    store.upsert_plan("session-1", steps)

    plan = store.get_plan("session-1")
    assert plan is not None
    assert isinstance(plan, PlanDocument)
    assert plan.session_id == "session-1"
    assert plan.steps == steps
    assert plan.status == PlanStatus.DRAFT


def test_upsert_overwrites_existing_plan(store: PlanStore) -> None:
    store.upsert_plan("session-2", ["old step"])
    store.upsert_plan("session-2", ["new step A", "new step B"])

    plan = store.get_plan("session-2")
    assert plan is not None
    assert plan.steps == ["new step A", "new step B"]
    # Status reset to draft on upsert.
    assert plan.status == PlanStatus.DRAFT


def test_get_plan_unknown_session_returns_none(store: PlanStore) -> None:
    result = store.get_plan("does-not-exist")
    assert result is None


# ---------------------------------------------------------------------------
# approve / reject transitions
# ---------------------------------------------------------------------------


def test_approve_updates_status(store: PlanStore) -> None:
    store.upsert_plan("session-3", ["do something"])
    store.approve("session-3", actor="alice", note="Looks good")

    plan = store.get_plan("session-3")
    assert plan is not None
    assert plan.status == PlanStatus.APPROVED


def test_approve_appends_approval_record(store: PlanStore) -> None:
    store.upsert_plan("session-4", ["step"])
    store.approve("session-4", actor="bob", note="LGTM")

    approvals = store.list_approvals("session-4")
    assert len(approvals) == 1
    rec = approvals[0]
    assert isinstance(rec, ApprovalRecord)
    assert rec.session_id == "session-4"
    assert rec.decision == PlanStatus.APPROVED
    assert rec.actor == "bob"
    assert rec.note == "LGTM"


def test_reject_updates_status(store: PlanStore) -> None:
    store.upsert_plan("session-5", ["step"])
    store.reject("session-5", actor="carol", note="Needs revision")

    plan = store.get_plan("session-5")
    assert plan is not None
    assert plan.status == PlanStatus.REJECTED


def test_reject_appends_approval_record(store: PlanStore) -> None:
    store.upsert_plan("session-6", ["step"])
    store.reject("session-6", actor="dave", note="Not ready")

    approvals = store.list_approvals("session-6")
    assert len(approvals) == 1
    rec = approvals[0]
    assert rec.decision == PlanStatus.REJECTED
    assert rec.actor == "dave"


def test_multiple_approvals_accumulate(store: PlanStore) -> None:
    """Approve then reject appends two records and final status is rejected."""
    store.upsert_plan("session-7", ["step"])
    store.approve("session-7", actor="alice")
    store.reject("session-7", actor="bob", note="Reverted after review")

    plan = store.get_plan("session-7")
    assert plan is not None
    assert plan.status == PlanStatus.REJECTED

    approvals = store.list_approvals("session-7")
    assert len(approvals) == 2
    assert approvals[0].decision == PlanStatus.APPROVED
    assert approvals[1].decision == PlanStatus.REJECTED


# ---------------------------------------------------------------------------
# list_plans
# ---------------------------------------------------------------------------


def test_list_plans_returns_all(store: PlanStore) -> None:
    store.upsert_plan("s-a", ["step a"])
    store.upsert_plan("s-b", ["step b"])
    store.upsert_plan("s-c", ["step c"])

    plans = store.list_plans()
    session_ids = {p.session_id for p in plans}
    assert {"s-a", "s-b", "s-c"}.issubset(session_ids)


def test_list_plans_empty_on_fresh_store(store: PlanStore) -> None:
    assert store.list_plans() == []


# ---------------------------------------------------------------------------
# Idempotent table creation
# ---------------------------------------------------------------------------


def test_table_creation_is_idempotent(tmp_path) -> None:
    """Constructing PlanStore twice on the same path must not raise."""
    db_path = tmp_path / "idempotent.db"
    s1 = PlanStore(db_path=db_path)
    s2 = PlanStore(db_path=db_path)
    s1.upsert_plan("x", ["step"])
    plan = s2.get_plan("x")
    assert plan is not None
    assert plan.steps == ["step"]
