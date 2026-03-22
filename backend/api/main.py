"""FastAPI application exposing orchestrator endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Dict, List

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.orchestrator.service import (
    AgentExecution,
    OrchestratorConfig,
    OrchestratorRun,
    OrchestratorService,
    PlanSession,
    RunSummary,
    SessionSummary,
)


class PlanRequest(BaseModel):
    goal: str = Field(..., description="High level goal provided by the user")


class PlanResponse(BaseModel):
    session_id: str
    goal: str
    plan: List[str]
    status: str


class ChatRequest(BaseModel):
    session_id: str
    message: str


class AgentExecutionModel(BaseModel):
    agent: str
    content: str
    metadata: Dict[str, object]


class HistoryItemModel(BaseModel):
    role: str
    content: str


class ChatResponse(BaseModel):
    run_id: str
    session_id: str
    status: str
    history: List[HistoryItemModel]
    results: List[AgentExecutionModel]


class SessionResponse(BaseModel):
    session_id: str
    goal: str
    plan: List[str]
    status: str
    history: List[HistoryItemModel]


class RunResponse(BaseModel):
    run_id: str
    session_id: str
    status: str
    trigger_message: str
    created_at: str
    results: List[AgentExecutionModel]


@lru_cache(maxsize=1)
def get_orchestrator() -> OrchestratorService:
    return OrchestratorService(config=OrchestratorConfig())


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_orchestrator()
    yield


app = FastAPI(title="AutoDev Orchestrator", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/plan", response_model=PlanResponse, tags=["planning"])
def create_plan(request: PlanRequest, orchestrator: OrchestratorService = Depends(get_orchestrator)) -> PlanResponse:
    plan_session: PlanSession = orchestrator.create_plan(request.goal)
    return PlanResponse(**plan_session.to_dict())


@app.get("/sessions", response_model=List[SessionResponse], tags=["sessions"])
def list_sessions(orchestrator: OrchestratorService = Depends(get_orchestrator)) -> List[SessionResponse]:
    sessions = orchestrator.list_sessions()
    return [
        SessionResponse(
            session_id=session.session_id,
            goal=session.goal,
            plan=session.plan,
            status=session.status,
            history=[HistoryItemModel(role=item.role, content=item.content) for item in session.history],
        )
        for session in sessions
    ]


@app.get("/sessions/{session_id}", response_model=SessionResponse, tags=["sessions"])
def get_session(
    session_id: str,
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> SessionResponse:
    try:
        session: SessionSummary = orchestrator.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SessionResponse(
        session_id=session.session_id,
        goal=session.goal,
        plan=session.plan,
        status=session.status,
        history=[HistoryItemModel(role=item.role, content=item.content) for item in session.history],
    )


@app.get("/sessions/{session_id}/runs", response_model=List[RunResponse], tags=["runs"])
def list_runs(
    session_id: str,
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> List[RunResponse]:
    try:
        runs = orchestrator.list_runs(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return [_to_run_response(run) for run in runs]


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
def chat(
    request: ChatRequest,
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> ChatResponse:
    try:
        run: OrchestratorRun = orchestrator.handle_message(request.session_id, request.message)
    except KeyError as exc:  # pragma: no cover - exercised via tests
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ChatResponse(
        run_id=run.run_id,
        session_id=run.session_id,
        status=run.status,
        history=[HistoryItemModel(role=item.role, content=item.content) for item in run.history],
        results=[_to_agent_execution_model(result) for result in run.results],
    )


def _to_run_response(run: RunSummary) -> RunResponse:
    return RunResponse(
        run_id=run.run_id,
        session_id=run.session_id,
        status=run.status,
        trigger_message=run.trigger_message,
        created_at=run.created_at,
        results=[_to_agent_execution_model(result) for result in run.results],
    )


def _to_agent_execution_model(result: AgentExecution) -> AgentExecutionModel:
    return AgentExecutionModel(agent=result.agent, content=result.content, metadata=dict(result.metadata))


__all__ = ["app"]
