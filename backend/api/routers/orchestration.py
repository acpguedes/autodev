"""Dynamic orchestration router — U8.

Adds a single opt-in endpoint:

    POST /chat/dynamic   body: {session_id, message}

When ``AUTODEV_DYNAMIC_ORCH=1`` is set in the environment the handler builds
a run-type-routed LangGraph via ``backend.orchestrator.routing`` and
``backend.orchestrator.graphs`` (merged in U7) and invokes it.  If the env
flag is absent, or if any import from those modules fails, it falls back to
the standard ``OrchestratorService.handle_message`` path so the endpoint is
always available and never breaks the baseline suite.

This router is auto-included by ``backend.api.routers.include_all_routers()``
— no changes to ``main.py`` are required.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["orchestration"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class DynamicChatRequest(BaseModel):
    session_id: str
    message: str


class DynamicChatResponse(BaseModel):
    run_id: str
    session_id: str
    status: str
    run_type: str
    current_state: str
    mode: str  # "dynamic" | "fallback"
    results: list[Dict[str, Any]] = []
    steps: list[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Dependency — reuse the same lru_cache'd orchestrator as main.py
# ---------------------------------------------------------------------------


def _get_orchestrator() -> Any:
    try:
        from backend.api.main import get_orchestrator  # noqa: PLC0415
        return get_orchestrator()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="orchestrator unavailable") from exc


# ---------------------------------------------------------------------------
# Dynamic execution helper
# ---------------------------------------------------------------------------


def _run_dynamic(orchestrator: Any, session_id: str, message: str) -> DynamicChatResponse:
    """Build a run-type-routed LangGraph and invoke it for *session_id*."""
    from backend.orchestrator.routing import RunTypeRouter  # noqa: PLC0415
    from backend.orchestrator.graphs import build_graph_for_run_type  # noqa: PLC0415
    from backend.orchestrator.service import (  # noqa: PLC0415
        AgentContext,
        AgentGraphState,
        RunStatus,
        RunType,
    )
    from uuid import uuid4  # noqa: PLC0415

    store = orchestrator._store
    session_record = store.get_session(session_id)
    if session_record is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")

    run_type: RunType = orchestrator._infer_run_type(
        goal=session_record["goal"], message=message
    )

    agents = orchestrator._agents
    router_inst = RunTypeRouter()

    try:
        graph = build_graph_for_run_type(agents, run_type, router_inst)
    except (ValueError, KeyError) as exc:
        logger.warning("build_graph_for_run_type failed (%s), falling back", exc)
        raise RuntimeError("graph build failed") from exc

    history_records = store.list_messages(session_id)
    from backend.orchestrator.service import HistoryItem  # noqa: PLC0415
    history = [HistoryItem(role=r["role"], content=r["content"]) for r in history_records]
    user_entry = HistoryItem(role="user", content=message)

    context = AgentContext(
        session_id=session_id,
        goal=session_record["goal"],
        user_request=message,
        history=[item.to_dict() for item in history] + [user_entry.to_dict()],
        artifacts=dict(session_record["artifacts"] or {}),
    )
    run_id = str(uuid4())
    initial_state: AgentGraphState = {
        "context": context,
        "results": [],
        "steps": [],
        "current_state": "starting",
        "run_id": run_id,
    }

    final_state = graph.invoke(initial_state)
    results = list(final_state["results"])
    steps = list(final_state["steps"])
    current_state = final_state["current_state"]

    return DynamicChatResponse(
        run_id=run_id,
        session_id=session_id,
        status=RunStatus.COMPLETED,
        run_type=str(run_type),
        current_state=current_state,
        mode="dynamic",
        results=[
            {"agent": r.agent, "content": r.content, "metadata": dict(r.metadata)}
            for r in results
        ],
        steps=[s.to_dict() for s in steps],
    )


# ---------------------------------------------------------------------------
# Fallback execution helper
# ---------------------------------------------------------------------------


def _run_fallback(orchestrator: Any, session_id: str, message: str) -> DynamicChatResponse:
    """Delegate to the standard ``OrchestratorService.handle_message``."""
    try:
        run = orchestrator.handle_message(session_id, message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DynamicChatResponse(
        run_id=run.run_id,
        session_id=run.session_id,
        status=run.status,
        run_type=run.run_type,
        current_state=run.current_state,
        mode="fallback",
        results=[
            {"agent": r.agent, "content": r.content, "metadata": dict(r.metadata)}
            for r in run.results
        ],
        steps=[s.to_dict() for s in run.steps],
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/chat/dynamic", response_model=DynamicChatResponse)
def dynamic_chat(
    body: DynamicChatRequest,
    orchestrator: Any = Depends(_get_orchestrator),
) -> DynamicChatResponse:
    """Send a message through the dynamic routing path (opt-in via env flag).

    When ``AUTODEV_DYNAMIC_ORCH=1`` the run is routed through a LangGraph
    built by ``backend.orchestrator.graphs.build_graph_for_run_type``.
    Otherwise (or on any import/build failure) falls back to the standard
    ``OrchestratorService.handle_message``.
    """
    dynamic_enabled = os.environ.get("AUTODEV_DYNAMIC_ORCH", "").strip() == "1"

    if dynamic_enabled:
        try:
            return _run_dynamic(orchestrator, body.session_id, body.message)
        except (ImportError, RuntimeError) as exc:
            logger.warning(
                "Dynamic routing unavailable (%s) — falling back to standard path", exc
            )

    return _run_fallback(orchestrator, body.session_id, body.message)
