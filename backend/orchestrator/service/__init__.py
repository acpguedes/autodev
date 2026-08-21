"""Service responsible for coordinating agent executions.

Split by concern across this package (E47-S5): see ``models`` (dataclasses/
enums), ``task_builders`` (T3), ``task_outcomes`` (T2), ``environment_scope``
(T1), ``summaries`` and ``message_job`` (T4), and the ``OrchestratorService``
mixins in ``chat``/``queries``/``plan_lifecycle``/``task_dispatch``/
``self_repair``/``graph`` composed by ``core``. This module keeps the same
import surface the single-file module previously exposed.
"""

from __future__ import annotations

from backend.agents import AgentContext
from backend.orchestrator.service.core import OrchestratorConfig, OrchestratorService
from backend.orchestrator.service.message_job import build_default_orchestrator
from backend.orchestrator.service.models import (
    AgentExecution,
    AgentGraphState,
    ExecutionPlan,
    ExecutionTask,
    HistoryItem,
    OrchestratorRun,
    PlanSession,
    RunStatus,
    RunStep,
    RunSummary,
    RunType,
    SessionSummary,
    StepStatus,
)

__all__ = [
    "AgentContext",
    "AgentExecution",
    "AgentGraphState",
    "ExecutionPlan",
    "ExecutionTask",
    "HistoryItem",
    "OrchestratorConfig",
    "OrchestratorRun",
    "OrchestratorService",
    "PlanSession",
    "RunStatus",
    "RunStep",
    "RunSummary",
    "RunType",
    "SessionSummary",
    "StepStatus",
    "build_default_orchestrator",
]
