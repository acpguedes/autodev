"""FastAPI application exposing orchestrator endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Dict, List

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.orchestrator.service import (
    AgentExecution,
    OrchestratorConfig,
    OrchestratorRun,
    OrchestratorService,
    PlanSession,
    RunStep,
    RunSummary,
    SessionSummary,
)

from backend.repository import RepositoryContext, RepositoryIntelligenceService


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


class RunStepModel(BaseModel):
    step_key: str
    agent: str
    status: str
    started_at: str
    completed_at: str
    attempt: int


class HistoryItemModel(BaseModel):
    role: str
    content: str


class RepositoryFileMatchModel(BaseModel):
    path: str
    score: int
    reasons: List[str]


class RepositoryContextResponse(BaseModel):
    query: str
    root: str
    total_files: int
    top_directories: List[str]
    candidate_files: List[RepositoryFileMatchModel]
    inventory_sample: List[str]
    matched_terms: List[str]


class ChatResponse(BaseModel):
    run_id: str
    session_id: str
    status: str
    run_type: str
    current_state: str
    history: List[HistoryItemModel]
    results: List[AgentExecutionModel]
    steps: List[RunStepModel]


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
    run_type: str
    current_state: str
    trigger_message: str
    created_at: str
    results: List[AgentExecutionModel]
    steps: List[RunStepModel]


@lru_cache(maxsize=1)
def get_orchestrator() -> OrchestratorService:
    return OrchestratorService(config=OrchestratorConfig())


@lru_cache(maxsize=1)
def get_repository_intelligence() -> RepositoryIntelligenceService:
    return RepositoryIntelligenceService(project_root=Path.cwd())


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


@app.get("/repository/context", response_model=RepositoryContextResponse, tags=["repository"])
def get_repository_context(
    query: str = "",
    limit: int = 8,
    repository_intelligence: RepositoryIntelligenceService = Depends(get_repository_intelligence),
) -> RepositoryContextResponse:
    repository_context: RepositoryContext = repository_intelligence.build_context(query=query, limit=max(1, min(limit, 25)))
    return RepositoryContextResponse(
        query=repository_context.query,
        root=repository_context.root,
        total_files=repository_context.total_files,
        top_directories=repository_context.top_directories,
        candidate_files=[
            RepositoryFileMatchModel(path=item.path, score=item.score, reasons=item.reasons)
            for item in repository_context.candidate_files
        ],
        inventory_sample=repository_context.inventory_sample,
        matched_terms=repository_context.matched_terms,
    )


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
        run_type=run.run_type,
        current_state=run.current_state,
        history=[HistoryItemModel(role=item.role, content=item.content) for item in run.history],
        results=[_to_agent_execution_model(result) for result in run.results],
        steps=[_to_run_step_model(step) for step in run.steps],
    )


def _to_run_response(run: RunSummary) -> RunResponse:
    return RunResponse(
        run_id=run.run_id,
        session_id=run.session_id,
        status=run.status,
        run_type=run.run_type,
        current_state=run.current_state,
        trigger_message=run.trigger_message,
        created_at=run.created_at,
        results=[_to_agent_execution_model(result) for result in run.results],
        steps=[_to_run_step_model(step) for step in run.steps],
    )


def _to_agent_execution_model(result: AgentExecution) -> AgentExecutionModel:
    return AgentExecutionModel(agent=result.agent, content=result.content, metadata=dict(result.metadata))


def _to_run_step_model(step: RunStep) -> RunStepModel:
    return RunStepModel(
        step_key=step.step_key,
        agent=step.agent,
        status=step.status,
        started_at=step.started_at,
        completed_at=step.completed_at,
        attempt=step.attempt,
    )


__all__ = ["app"]
