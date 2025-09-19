"""FastAPI application exposing orchestrator endpoints."""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, List

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from backend.orchestrator.service import (
    OrchestratorConfig,
    OrchestratorRun,
    OrchestratorService,
    PlanSession,
)


class PlanRequest(BaseModel):
    goal: str = Field(..., description="High level goal provided by the user")


class PlanResponse(BaseModel):
    session_id: str
    goal: str
    plan: List[str]


class ChatRequest(BaseModel):
    session_id: str
    message: str


class AgentExecutionModel(BaseModel):
    agent: str
    content: str
    metadata: Dict[str, object]


class ChatResponse(BaseModel):
    session_id: str
    history: List[str]
    results: List[AgentExecutionModel]


@lru_cache(maxsize=1)
def get_orchestrator() -> OrchestratorService:
    return OrchestratorService(config=OrchestratorConfig())


app = FastAPI(title="AutoDev Orchestrator", version="0.1.0")


@app.get("/health", tags=["meta"])
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/plan", response_model=PlanResponse, tags=["planning"])
def create_plan(request: PlanRequest, orchestrator: OrchestratorService = Depends(get_orchestrator)) -> PlanResponse:
    plan_session: PlanSession = orchestrator.create_plan(request.goal)
    return PlanResponse(**plan_session.to_dict())


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
def chat(
    request: ChatRequest,
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> ChatResponse:
    try:
        run: OrchestratorRun = orchestrator.handle_message(request.session_id, request.message)
    except KeyError as exc:  # pragma: no cover - exercised via tests
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    results = [
        AgentExecutionModel(agent=result.agent, content=result.content, metadata=dict(result.metadata))
        for result in run.results
    ]
    return ChatResponse(session_id=run.session_id, history=list(run.history), results=results)


__all__ = ["app"]
