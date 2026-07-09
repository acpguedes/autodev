"""FastAPI application exposing orchestrator endpoints."""

# ruff: noqa: E402  — load_dotenv must run before third-party imports

from __future__ import annotations

import html as _html

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Final, List

import sys

from dotenv import load_dotenv

# Pin the dotenv path to this repo's root so python-dotenv's upward search
# cannot escape a nested git worktree into a parent checkout's .env. Under
# pytest, do not override env vars already set by the harness (preserves test
# isolation); production imports still refresh from .env.
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH, override="pytest" not in sys.modules)

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from backend.api.security import require_api_token
from backend.api.security_headers import SecurityHeadersMiddleware

from backend.artifacts import get_artifact_store
from backend.config import (
    RuntimeConfig,
    RuntimeConfigService,
    RuntimeInstructions,
    get_runtime_config_service,
)
from backend.config.settings import get_settings
from backend.coordination import get_cache, get_lock_manager
from backend.jobs.queue import get_queue
from backend.llm.factory import get_chat_model
from backend.observability.tracing import configure_tracing
from backend.orchestrator.service import (
    AgentExecution,
    ExecutionPlan,
    ExecutionTask,
    OrchestratorConfig,
    OrchestratorRun,
    OrchestratorService,
    PlanSession,
    RunStep,
    RunSummary,
    SessionSummary,
)
from backend.api.routers import include_all_routers
from backend.repository import RepositoryContext, RepositoryIntelligenceService


class PlanRequest(BaseModel):
    """Request body for ``POST /plan``."""
    goal: str = Field(..., description="High level goal provided by the user")


class PlanResponse(BaseModel):
    """Response body describing a newly created planning session."""
    session_id: str
    goal: str
    plan: List[str]
    status: str


class ChatRequest(BaseModel):
    """Request body for ``POST /chat``."""
    session_id: str
    message: str


class AgentExecutionModel(BaseModel):
    """API representation of a single agent execution result."""
    agent: str
    content: str
    metadata: Dict[str, object]


class RunStepModel(BaseModel):
    """API representation of a single orchestration run step."""
    step_key: str
    agent: str
    status: str
    started_at: str
    completed_at: str
    attempt: int


class HistoryItemModel(BaseModel):
    """API representation of a single conversation history entry."""
    role: str
    content: str


class RepositoryFileMatchModel(BaseModel):
    """API representation of a single repository search match."""
    path: str
    score: int
    reasons: List[str]


class RepositoryContextResponse(BaseModel):
    """Response body for ``GET /repository/context``."""
    query: str
    root: str
    total_files: int
    top_directories: List[str]
    candidate_files: List[RepositoryFileMatchModel]
    inventory_sample: List[str]
    matched_terms: List[str]


class ChatResponse(BaseModel):
    """Response body for endpoints returning a completed orchestration run."""
    run_id: str
    session_id: str
    status: str
    run_type: str
    current_state: str
    history: List[HistoryItemModel]
    results: List[AgentExecutionModel]
    steps: List[RunStepModel]


class SessionResponse(BaseModel):
    """Response body describing a single orchestration session."""
    session_id: str
    goal: str
    plan: List[str]
    status: str
    history: List[HistoryItemModel]


class RunResponse(BaseModel):
    """Response body describing a single historical orchestration run."""
    run_id: str
    session_id: str
    status: str
    run_type: str
    current_state: str
    trigger_message: str
    created_at: str
    results: List[AgentExecutionModel]
    steps: List[RunStepModel]


class RuntimeConfigResponse(BaseModel):
    """Response body for ``GET``/``PUT /config``."""
    config: RuntimeConfig
    instructions: RuntimeInstructions


class RuntimeConfigUpdateRequest(BaseModel):
    """Request body for ``PUT /config``."""
    config: RuntimeConfig


class AgentContractsResponse(BaseModel):
    """Response body for ``GET /agents/contracts``."""
    contracts: Dict[str, Dict[str, Any]]


class ExecutionTaskModel(BaseModel):
    """API representation of a single execution-plan task."""
    task_id: str
    title: str
    description: str
    source_agent: str
    category: str
    status: str


class ExecutionPlanResponse(BaseModel):
    """Response body for ``GET /sessions/{session_id}/execution-plan``."""
    session_id: str
    summary: str
    analysis_summary: str
    tasks: List[ExecutionTaskModel]
    status: str


@lru_cache(maxsize=1)
def get_orchestrator() -> OrchestratorService:
    """Build and cache the process-wide :class:`OrchestratorService` instance."""
    config_service = get_runtime_config_service()
    runtime_config = config_service.apply_to_environment()
    get_chat_model.cache_clear()
    return OrchestratorService(
        config=OrchestratorConfig(),
        project_root=Path(runtime_config.repository.project_root),
    )


@lru_cache(maxsize=1)
def get_repository_intelligence() -> RepositoryIntelligenceService:
    """Build and cache the process-wide :class:`RepositoryIntelligenceService` instance."""
    config_service = get_runtime_config_service()
    runtime_config = config_service.apply_to_environment()
    return RepositoryIntelligenceService(project_root=Path(runtime_config.repository.project_root))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize infrastructure clients and the orchestrator on app startup."""
    settings = get_settings()
    configure_tracing(settings)
    if settings.autodev_profile == "prod":
        get_cache(settings)
        get_lock_manager(settings)
        get_artifact_store(settings)
        get_queue(settings)
    get_runtime_config_service().apply_to_environment()
    get_orchestrator()
    yield


# Single source of truth for the API name/version, shared between the FastAPI
# metadata (OpenAPI ``info``) and the ``GET /`` service descriptor.
API_TITLE: Final[str] = "AutoDev Orchestrator"
API_VERSION: Final[str] = "0.3.0"

app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    lifespan=lifespan,
    # Global gate — a no-op unless AUTODEV_API_TOKEN is configured.
    dependencies=[Depends(require_api_token)],
)


def _cors_allowed_origins() -> List[str]:
    """Resolve CORS origins, allowing deployment-time override.

    Defaults to the local Next.js dev server. Set ``AUTODEV_CORS_ORIGINS`` to a
    comma-separated list to override for other deployments.
    """
    return get_settings().cors_origins()


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(SecurityHeadersMiddleware)

try:
    include_all_routers(app)
except Exception:
    import logging as _logging
    _logging.getLogger(__name__).exception("Router auto-loader failed — continuing without plugin routers")


# CSP-clean pointer page for humans who browse the API origin directly: no
# script, no style, no external assets — only same-origin links plus the UI
# URL, so it renders under the unchanged ``default-src 'self'`` policy. This
# is deliberately not a product UI (v2 reference §2.13): the backend only
# describes and points to the real frontend.
_FRONT_DOOR_HTML_TEMPLATE: Final[str] = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
</head>
<body>
<h1>{title}</h1>
<p>This origin serves the AutoDev control-plane API, not the product UI.
Open the <a href="{ui_url}">Control Center</a> to use AutoDev, browse the
<a href="/docs">API documentation</a>, or check the
<a href="/health">health endpoint</a>.</p>
</body>
</html>
"""


def _prefers_html(accept_header: str) -> bool:
    """Return ``True`` when the ``Accept`` header asks for an HTML document.

    Uses a deliberately small heuristic instead of full RFC 9110 content
    negotiation: the header is split on commas and each media type is compared
    (ignoring ``q=`` and other parameters) against the HTML types browsers
    send. API clients sending ``*/*`` or ``application/json`` get JSON.

    Args:
        accept_header: Raw ``Accept`` header value (may be empty).

    Returns:
        ``True`` if ``text/html`` or ``application/xhtml+xml`` is offered.
    """
    offered = {part.split(";")[0].strip().lower() for part in accept_header.split(",")}
    return bool(offered & {"text/html", "application/xhtml+xml"})


@app.get("/", tags=["meta"], response_model=None, include_in_schema=True)
def service_descriptor(request: Request) -> Response:
    """Describe the service and point clients at the UI, docs, and health.

    Content-negotiated front door for the API origin: API clients receive a
    JSON service descriptor, while browsers (``Accept: text/html``) receive a
    minimal CSP-clean pointer page linking to the Control Center UI.

    Args:
        request: Incoming request, used for ``Accept``-header negotiation.

    Returns:
        A ``JSONResponse`` descriptor or an ``HTMLResponse`` pointer page.
    """
    # Read settings per-request so AUTODEV_UI_URL overrides (and test cache
    # resets) take effect without a process restart.
    ui_url = get_settings().autodev_ui_url
    if _prefers_html(request.headers.get("accept", "")):
        page = _FRONT_DOOR_HTML_TEMPLATE.format(
            title=_html.escape(API_TITLE),
            ui_url=_html.escape(ui_url, quote=True),
        )
        return HTMLResponse(content=page)
    return JSONResponse(
        content={
            "name": API_TITLE,
            "version": API_VERSION,
            "description": (
                "API-first control plane for AutoDev. The product UI is a "
                "separate Next.js app served at ui_url."
            ),
            "ui_url": ui_url,
            "docs_url": "/docs",
            "health_url": "/health",
            "openapi_url": "/openapi.json",
            "api": {"v2_base": "/v2"},
        }
    )


@app.get("/health", tags=["meta"])
def healthcheck() -> Dict[str, str]:
    """Report basic liveness of the API process."""
    return {"status": "ok"}


@app.get("/config", response_model=RuntimeConfigResponse, tags=["config"])
def get_runtime_config(
    config_service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> RuntimeConfigResponse:
    """Return the current runtime configuration with secrets redacted."""
    document = config_service.load_document(redact_secrets=True)
    return RuntimeConfigResponse(config=document.config, instructions=document.instructions)


@app.put("/config", response_model=RuntimeConfigResponse, tags=["config"])
def update_runtime_config(
    request: RuntimeConfigUpdateRequest,
    config_service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> RuntimeConfigResponse:
    """Persist a new runtime configuration and apply it to the process."""
    saved_config = config_service.update(request.config)
    config_service.apply_to_environment(saved_config)
    get_chat_model.cache_clear()
    get_orchestrator.cache_clear()
    get_repository_intelligence.cache_clear()
    document = config_service.load_document(redact_secrets=True)
    return RuntimeConfigResponse(config=document.config, instructions=document.instructions)


@app.get("/agents/contracts", response_model=AgentContractsResponse, tags=["agents"])
def get_agent_contracts(
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> AgentContractsResponse:
    """Describe the IO contracts declared by registered agents."""
    return AgentContractsResponse(contracts=orchestrator.describe_agent_contracts())


@app.post("/plan", response_model=PlanResponse, tags=["planning"])
def create_plan(request: PlanRequest, orchestrator: OrchestratorService = Depends(get_orchestrator)) -> PlanResponse:
    """Create a new planning session for a user-provided goal."""
    plan_session: PlanSession = orchestrator.create_plan(request.goal)
    return PlanResponse(**plan_session.to_dict())


@app.get("/sessions", response_model=List[SessionResponse], tags=["sessions"])
def list_sessions(orchestrator: OrchestratorService = Depends(get_orchestrator)) -> List[SessionResponse]:
    """List all known orchestration sessions."""
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
    """Fetch a single orchestration session by id. Raises HTTPException(404) if missing."""
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
    """List the historical orchestration runs for a session. Raises HTTPException(404) if missing."""
    try:
        runs = orchestrator.list_runs(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return [_to_run_response(run) for run in runs]


@app.get(
    "/sessions/{session_id}/execution-plan",
    response_model=ExecutionPlanResponse,
    tags=["planning"],
)
def get_execution_plan(
    session_id: str,
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> ExecutionPlanResponse:
    """Build the execution plan derived from a session's conversation so far.

    Raises HTTPException(404) if missing.
    """
    try:
        execution_plan: ExecutionPlan = orchestrator.build_execution_plan(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ExecutionPlanResponse(
        session_id=execution_plan.session_id,
        summary=execution_plan.summary,
        analysis_summary=execution_plan.analysis_summary,
        tasks=[_to_execution_task_model(task) for task in execution_plan.tasks],
        status=execution_plan.status,
    )


@app.post(
    "/sessions/{session_id}/execution-plan/execute",
    response_model=ChatResponse,
    tags=["planning"],
)
def execute_execution_plan(
    session_id: str,
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> ChatResponse:
    """Execute a session's derived execution plan.

    Raises HTTPException(404) if missing, or (400) if there is no executable plan.
    """
    try:
        run: OrchestratorRun = orchestrator.execute_plan(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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


@app.get("/repository/context", response_model=RepositoryContextResponse, tags=["repository"])
def get_repository_context(
    query: str = "",
    limit: int = 8,
    repository_intelligence: RepositoryIntelligenceService = Depends(get_repository_intelligence),
) -> RepositoryContextResponse:
    """Search the repository for files relevant to a free-text query. ``limit`` is clamped to 1-25."""
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
    """Send a chat message into an existing session and run the orchestrator.

    Raises HTTPException(404) if missing.
    """
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
    """Convert an orchestrator run summary into its API response model."""
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
    """Convert an agent execution result into its API response model."""
    return AgentExecutionModel(agent=result.agent, content=result.content, metadata=dict(result.metadata))


def _to_run_step_model(step: RunStep) -> RunStepModel:
    """Convert an orchestration run step into its API response model."""
    return RunStepModel(
        step_key=step.step_key,
        agent=step.agent,
        status=step.status,
        started_at=step.started_at,
        completed_at=step.completed_at,
        attempt=step.attempt,
    )


def _to_execution_task_model(task: ExecutionTask) -> ExecutionTaskModel:
    """Convert an execution-plan task into its API response model."""
    return ExecutionTaskModel(
        task_id=task.task_id,
        title=task.title,
        description=task.description,
        source_agent=task.source_agent,
        category=task.category,
        status=task.status,
    )


__all__ = ["app", "get_orchestrator", "get_repository_intelligence"]
