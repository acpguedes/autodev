"""Data model — dataclasses, enums, and the LangGraph state shape used by the orchestrator (E47-S5)."""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Fallback StrEnum compatible with Python 3.10."""

        pass


from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, NotRequired, Optional, TypedDict

from backend.agents import AgentContext
from backend.execution.contracts import ExecutionResult
from backend.execution.executor import TaskExecutionOutcome


@dataclass(slots=True)
class HistoryItem:
    """Represents a single conversational turn."""

    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        """Render this history item as a plain dict."""
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class AgentExecution:
    """Result produced by an agent during orchestration."""

    agent: str
    content: str
    metadata: Mapping[str, Any]


class RunType(StrEnum):
    """Supported workflow types for orchestrator runs."""

    GREENFIELD_BOOTSTRAP = "greenfield_bootstrap"
    EXISTING_REPO_CHANGE = "existing_repo_change"
    DOCUMENTATION_UPDATE = "documentation_update"
    DEVOPS_CHANGE = "devops_change"
    VALIDATION_ONLY = "validation_only"
    PLAN_EXECUTION = "plan_execution"


class RunStatus(StrEnum):
    """Top-level states used by the explicit workflow engine slice."""

    AWAITING_INPUT = "awaiting_input"
    RUNNING = "running"
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    FAILED = "failed"


class StepStatus(StrEnum):
    """Execution status for an individual workflow step."""

    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"


@dataclass(slots=True)
class RunStep:
    """Represents a completed step within a run."""

    step_key: str
    agent: str
    status: str
    started_at: str
    completed_at: str
    attempt: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Render this run step as a plain dict."""
        return {
            "step_key": self.step_key,
            "agent": self.agent,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempt": self.attempt,
        }


@dataclass(slots=True)
class ExecutionTask:
    """Executable task derived from agent analysis artifacts."""

    task_id: str
    title: str
    description: str
    source_agent: str
    category: str
    status: str = "pending"
    files: List[Dict[str, str]] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Render this execution task as a plain dict."""
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "source_agent": self.source_agent,
            "category": self.category,
            "status": self.status,
            "files": list(self.files),
            "commands": list(self.commands),
        }


@dataclass(slots=True)
class ExecutionPlan:
    """Step-by-step execution plan built from session artifacts."""

    session_id: str
    summary: str
    analysis_summary: str
    tasks: List[ExecutionTask]
    status: str


@dataclass(slots=True)
class OrchestratorRun:
    """Aggregate response returned to the API layer."""

    run_id: str
    session_id: str
    status: str
    run_type: str
    current_state: str
    history: List[HistoryItem]
    results: List[AgentExecution]
    steps: List[RunStep]

    def to_dict(self) -> Dict[str, Any]:
        """Render this run as a plain dict for the API layer."""
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": self.status,
            "run_type": self.run_type,
            "current_state": self.current_state,
            "history": [item.to_dict() for item in self.history],
            "results": [
                {
                    "agent": result.agent,
                    "content": result.content,
                    "metadata": dict(result.metadata),
                }
                for result in self.results
            ],
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(slots=True)
class PreparedRun:
    """Result of ``OrchestratorService._prepare_run`` (E43-S6).

    Everything a new message-driven run needs before its graph is actually
    invoked: the session it belongs to, its already-persisted (and
    lease-admitted) run id, its inferred type, and its observability flow id.
    """

    session_record: Dict[str, Any]
    run_id: str
    run_type: "RunType"
    flow_id: str


@dataclass(slots=True)
class PlanSession:
    """Data returned after generating a plan."""

    session_id: str
    goal: str
    plan: List[str]
    status: str = RunStatus.AWAITING_INPUT

    def to_dict(self) -> Dict[str, Any]:
        """Render this plan session as a plain dict."""
        return {
            "session_id": self.session_id,
            "goal": self.goal,
            "plan": list(self.plan),
            "status": self.status,
        }


@dataclass(slots=True)
class SessionSummary:
    """Session details exposed by the API.

    Attributes:
        session_id: Identifier of the session.
        goal: The session's stated goal.
        plan: Ordered plan step descriptions.
        status: The session's current status.
        history: The conversation so far. Populated when a single session is
            fetched; intentionally empty in listings, which derive
            ``message_count``/``last_activity`` from an aggregate instead of
            replaying every session's messages (E44-S3).
        message_count: Number of messages recorded for the session.
        last_activity: Timestamp of the most recent message, or ``None`` when
            the session has none yet.
    """

    session_id: str
    goal: str
    plan: List[str]
    status: str
    history: List[HistoryItem]
    message_count: int = 0
    last_activity: Optional[str] = None


@dataclass(slots=True)
class RunSummary:
    """Stored run details for history endpoints."""

    run_id: str
    session_id: str
    status: str
    run_type: str
    current_state: str
    trigger_message: str
    created_at: str
    results: List[AgentExecution]
    steps: List[RunStep]


@dataclass(slots=True)
class OrchestratorConfig:
    """Configuration values for the orchestrator service."""

    agent_order: Iterable[str] = (
        "navigator",
        "analyzer",
        "architect",
        "coder",
        "devops",
        "validator",
        "responder",
    )


class AgentGraphState(TypedDict):
    """State propagated through the LangGraph workflow.

    Attributes:
        tenant_id: Tenant this run belongs to, used to emit live
            ``run.timeline.*`` events per completed agent node (E43-S6).
            Optional so the dynamic-routing graph built by
            ``backend/orchestrator/graphs.py`` (a separate node-builder,
            unaffected by this) and any other existing construction of this
            state keep working unchanged.
    """

    context: AgentContext
    results: List[AgentExecution]
    steps: List[RunStep]
    current_state: str
    run_id: str
    tenant_id: NotRequired[str]


_TIMELINE_OUTPUT_CHAR_CAP = 8000
"""Max length of one ``run.timeline.*`` event's ``output`` text (E42-S5).

Keeps a single event's payload bounded regardless of how much stdout/stderr
a task's actions captured; the tail is kept since that's what a validation
failure's relevant output usually is.
"""


def build_timeline_output(results: Iterable[ExecutionResult]) -> str:
    """Concatenate a task's captured stdout/stderr into one log excerpt.

    Sourced from :attr:`~backend.execution.contracts.ExecutionResult.stdout`/
    ``.stderr`` -- already captured per action (E41) but never surfaced live
    before this (E42-S5): a ``run.timeline.*`` event's ``output`` field is
    exactly the "monospace stdout/log excerpt" it was designed to carry
    (``backend.events.catalog.RunTimelineStepData``).

    Args:
        results: Per-action results from one task's execution, in dispatch
            order.

    Returns:
        The concatenated excerpt, tail-truncated to
        :data:`_TIMELINE_OUTPUT_CHAR_CAP`.
    """
    parts = [text for result in results for text in (result.stdout, result.stderr) if text]
    output = "\n".join(parts)
    if len(output) > _TIMELINE_OUTPUT_CHAR_CAP:
        output = output[-_TIMELINE_OUTPUT_CHAR_CAP:]
    return output


class DispatchRecord(NamedTuple):
    """One dispatched task's first-attempt outcome, pending self-repair rendering (E46-S3).

    Accumulated across a batch's dispatch pass so
    ``backend.orchestrator.service.task_dispatch`` can run one batched
    self-repair pass over every eligible task before appending any task's
    final ``AgentExecution``/``RunStep``/``HistoryItem`` entries, while still
    rendering every task in its original dispatch order.
    """

    display_index: int
    task: ExecutionTask
    started_at: str
    completed_at: str
    outcome: TaskExecutionOutcome


__all__ = [
    "AgentExecution",
    "AgentGraphState",
    "DispatchRecord",
    "ExecutionPlan",
    "ExecutionTask",
    "HistoryItem",
    "OrchestratorConfig",
    "OrchestratorRun",
    "PlanSession",
    "PreparedRun",
    "RunStatus",
    "RunStep",
    "RunSummary",
    "RunType",
    "SessionSummary",
    "StepStatus",
    "StrEnum",
    "build_timeline_output",
]
