"""Typing base declaring the instance state and cross-mixin calls every OrchestratorService mixin depends on (E47-S5).

``OrchestratorService`` (in :mod:`core`) sets the real instance attributes in
``__init__`` and composes every mixin, which together provide the real
implementation of each stub method below. This class exists only so each
mixin module can be read, and type-checked, without importing every other
mixin — the same pattern used for the persistence adapters' ``_ConnectionOwner``
(E47-S4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from backend.agents import Agent, AgentResult
from backend.environments.manager import EnvironmentManager
from backend.execution.contracts import ExecutionAction
from backend.execution.decisions import DecisionService
from backend.execution.executor import TaskExecutionOutcome, TaskExecutor
from backend.execution.modes import ExecutionMode
from backend.execution.policy import PendingDecision, PolicyService
from backend.execution.runner import InProcessActionRunner
from backend.orchestrator.service.models import (
    AgentExecution,
    ExecutionTask,
    HistoryItem,
    OrchestratorConfig,
    RunStep,
    RunType,
)
from backend.quotas.service import QuotaService


class OrchestratorState:
    """Instance-state and cross-mixin-method typing base for every OrchestratorService mixin."""

    _config: OrchestratorConfig
    _project_root: Optional[Path]
    _agents: Dict[str, Agent]
    # Untyped like the pre-split module: `get_store()` returns
    # `SQLiteStore | PostgresStore`, and every mixin only relies on the
    # common, un-narrowed repository-protocol surface (get_session,
    # list_messages, create_run, ...) both backends implement.
    _store: Any
    _quota_service: QuotaService
    _policy_service: PolicyService
    _decision_service: DecisionService
    _environment_manager: EnvironmentManager
    _composite_runner: InProcessActionRunner
    _task_executor: TaskExecutor
    _graph: Any

    def _timestamp(self) -> str:  # pragma: no cover - overridden by OrchestratorService
        raise NotImplementedError

    def _require_agent(self, name: str) -> Agent:  # pragma: no cover
        raise NotImplementedError

    def _clone_artifacts(
        self, artifacts: Mapping[str, Mapping[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def _infer_run_type(self, *, goal: str, message: str) -> RunType:  # pragma: no cover
        raise NotImplementedError

    def _normalize_execution_history(
        self, history: List[HistoryItem]
    ) -> List[HistoryItem]:  # pragma: no cover
        raise NotImplementedError

    def _extract_plan_steps(self, plan_result: AgentResult) -> List[str]:  # pragma: no cover
        raise NotImplementedError

    def _acquire_run_lease(self, *, tenant_id: str, run_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def _process_tasks(
        self,
        *,
        tasks: List[ExecutionTask],
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode,
        results: List[AgentExecution],
        steps: List[RunStep],
        history: List[HistoryItem],
        total_count: int,
        start_index: int,
    ) -> "tuple[str, bool]":  # pragma: no cover
        raise NotImplementedError

    def _resolve_task_actions(
        self,
        *,
        task: ExecutionTask,
        actions: List[ExecutionAction],
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode,
        environment_denied_reason: Optional[str] = None,
    ) -> "tuple[Optional[TaskExecutionOutcome], Optional[PendingDecision]]":  # pragma: no cover
        raise NotImplementedError

    def _maybe_batch_self_repair(
        self,
        candidates: List["tuple[ExecutionTask, TaskExecutionOutcome]"],
        *,
        batch_results: List[Any],
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode,
    ) -> "Dict[str, tuple[TaskExecutionOutcome, str]]":  # pragma: no cover
        raise NotImplementedError


__all__ = ["OrchestratorState"]
