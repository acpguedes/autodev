"""Plans API router — U10.

Exposes a CRUD + approval workflow for persisted plan documents:

    GET  /plans/{session_id}         — retrieve; 404 if absent.
    PUT  /plans/{session_id}         — upsert steps (resets status to draft).
    POST /plans/{session_id}/approve — approve; body {actor, note?}.
    POST /plans/{session_id}/reject  — reject;  body {actor, note?}.

Path prefix ``/plans`` is distinct from the existing ``/plan`` (POST, creates
sessions) and ``/sessions/{id}/execution-plan`` endpoints in main.py.

``backend.plans`` is lazily imported — the endpoint returns 503 when the
module is absent so the baseline suite is unaffected.

This router is auto-included by ``backend.api.routers.include_all_routers()``;
no changes to ``main.py`` are required.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["plans"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> Any:
    """Instantiate ``PlanStore`` from DATABASE_URL (or default)."""
    try:
        from backend.plans import PlanStore  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="plans subsystem unavailable"
        ) from exc

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("sqlite:///"):
        raw = db_url.removeprefix("sqlite:///")
        db_path: Optional[Path] = Path(raw).expanduser().resolve()
    else:
        db_path = None  # PlanStore falls back to DATABASE_URL env var itself

    return PlanStore(db_path=db_path)


def _require_plan(store: Any, session_id: str) -> Any:
    """Return the plan or raise 404."""
    plan = store.get_plan(session_id)
    if plan is None:
        raise HTTPException(
            status_code=404, detail=f"Plan for session {session_id!r} not found."
        )
    return plan


def _plan_to_dict(plan: Any) -> dict:
    return {
        "session_id": plan.session_id,
        "steps": plan.steps,
        "status": plan.status,
        "updated_at": plan.updated_at,
    }


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class PlanUpsertRequest(BaseModel):
    steps: List[str]


class ApprovalRequest(BaseModel):
    actor: str
    note: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/plans/{session_id}")
def get_plan(session_id: str) -> dict:
    """Return the plan document for *session_id*; 404 if not found."""
    store = _make_store()
    plan = _require_plan(store, session_id)
    return _plan_to_dict(plan)


@router.put("/plans/{session_id}")
def upsert_plan(session_id: str, body: PlanUpsertRequest) -> dict:
    """Insert or replace the steps for *session_id*.

    Resets plan status to ``draft`` on every upsert.
    """
    store = _make_store()
    store.upsert_plan(session_id, body.steps)
    plan = store.get_plan(session_id)
    return _plan_to_dict(plan)


@router.post("/plans/{session_id}/approve")
def approve_plan(session_id: str, body: ApprovalRequest) -> dict:
    """Approve the plan for *session_id*.

    404 if the plan does not exist yet.
    """
    store = _make_store()
    _require_plan(store, session_id)  # assert existence
    store.approve(session_id, actor=body.actor, note=body.note)
    plan = store.get_plan(session_id)
    return _plan_to_dict(plan)


@router.post("/plans/{session_id}/reject")
def reject_plan(session_id: str, body: ApprovalRequest) -> dict:
    """Reject the plan for *session_id*.

    404 if the plan does not exist yet.
    """
    store = _make_store()
    _require_plan(store, session_id)  # assert existence
    store.reject(session_id, actor=body.actor, note=body.note)
    plan = store.get_plan(session_id)
    return _plan_to_dict(plan)
