"""Execution-plan derivation, dispatch, resume, and human-decision resolution (E47-S5)."""

from __future__ import annotations

from typing import Any, List, Optional
from uuid import uuid4

from backend.execution.decisions import DecisionStatus
from backend.execution.modes import ExecutionMode
from backend.execution.policy import PendingDecision, PolicyEffect, PolicyRule, PolicyScopeKind
from backend.orchestrator.service._shared import OrchestratorState
from backend.orchestrator.service.models import (
    AgentExecution,
    ExecutionPlan,
    HistoryItem,
    OrchestratorRun,
    RunStatus,
    RunStep,
    RunType,
    StepStatus,
)
from backend.orchestrator.service.task_builders import build_execution_tasks
from backend.persistence.tenancy import DEFAULT_TENANT_ID


class PlanLifecycleMixin(OrchestratorState):
    """Derive, execute, resume, and finalize a session's task-execution plan."""

    def build_execution_plan(
        self, session_id: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> ExecutionPlan:
        """Derive an execution plan from a session's accumulated agent artifacts.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        session_record = self._store.get_session(session_id, tenant_id=tenant_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")

        artifacts = dict(session_record.get("artifacts") or {})
        analyzer_artifact = artifacts.get("analyzer", {})
        if not analyzer_artifact:
            return ExecutionPlan(
                session_id=session_id,
                summary="Execution plan unavailable until an analysis run has completed.",
                analysis_summary="No analyzer output available yet.",
                tasks=[],
                status=RunStatus.AWAITING_INPUT,
            )

        tasks = build_execution_tasks(
            plan_steps=list(session_record.get("plan") or []),
            artifacts=artifacts,
        )
        return ExecutionPlan(
            session_id=session_id,
            summary="Step-by-step execution plan derived from analysis, coding, devops, and validation artifacts.",
            analysis_summary=analyzer_artifact.get("summary", ""),
            tasks=tasks,
            status=RunStatus.AWAITING_INPUT if tasks else RunStatus.COMPLETED,
        )

    def execute_plan(
        self,
        session_id: str,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        mode: ExecutionMode = ExecutionMode.AUTO,
    ) -> OrchestratorRun:
        """Execute a session's derived execution plan and record the run.

        Args:
            session_id: Session to derive and execute the plan for.
            tenant_id: Tenant the session must belong to.
            mode: Execution mode (E14-S3) governing whether a task's
                actions run automatically, always pause for a human
                decision, or pause only when policy doesn't cover them.
                Defaults to :attr:`~backend.execution.modes.ExecutionMode.AUTO`.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
            ValueError: If the session has no executable tasks.
        """
        execution_plan = self.build_execution_plan(session_id, tenant_id=tenant_id)
        if not execution_plan.tasks:
            raise ValueError(
                "No executable tasks are available for the requested session."
            )

        run_id = str(uuid4())
        self._acquire_run_lease(tenant_id=tenant_id, run_id=run_id)
        try:
            return self._execute_plan_run(
                execution_plan=execution_plan,
                session_id=session_id,
                run_id=run_id,
                tenant_id=tenant_id,
                mode=mode,
            )
        finally:
            self._quota_service.release_run_lease(run_id)

    def resume_plan_execution(
        self,
        session_id: str,
        run_id: str,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        mode: ExecutionMode = ExecutionMode.AUTO,
    ) -> OrchestratorRun:
        """Resume a plan-execution run paused awaiting a human decision (E14-S3).

        Re-derives the execution plan (deterministic given unchanged
        session artifacts, the same call :meth:`execute_plan` already
        makes) and continues past every task that already has a terminal
        step, picking mode-aware processing back up from the first
        non-terminal task. No task-list snapshot is persisted separately —
        the stored run's own steps are the resume checkpoint.

        Args:
            session_id: Session the paused run belongs to.
            run_id: The paused run to resume.
            tenant_id: Tenant the session/run must belong to.
            mode: Execution mode for the resumed portion of the run —
                callers are expected to pass the same mode the run started
                with; mode is a per-call parameter, not persisted run state.

        Raises:
            KeyError: If ``session_id``/``run_id`` do not exist for ``tenant_id``.
            ValueError: If the run is not currently awaiting a decision.
        """
        session_record = self._store.get_session(session_id, tenant_id=tenant_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        run_record = self._find_run_record(session_id, run_id, tenant_id=tenant_id)
        if run_record is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        if run_record["status"] != RunStatus.AWAITING_APPROVAL:
            raise ValueError(
                f"Run {run_id!r} is not awaiting a decision (status={run_record['status']!r})."
            )

        execution_plan = self.build_execution_plan(session_id, tenant_id=tenant_id)
        existing_steps = [
            RunStep(
                step_key=item["step_key"],
                agent=item["agent"],
                status=item["status"],
                started_at=item["started_at"],
                completed_at=item["completed_at"],
                attempt=item.get("attempt", 1),
            )
            for item in (run_record["steps"] or [])
        ]
        existing_results = [
            AgentExecution(
                agent=item.get("agent", "unknown"),
                content=item.get("content", ""),
                metadata=item.get("metadata", {}),
            )
            for item in (run_record["results"] or [])
        ]
        terminal_task_ids = {
            step.step_key
            for step in existing_steps
            if step.status in (StepStatus.COMPLETED, StepStatus.FAILED)
        }
        remaining_tasks = [
            task for task in execution_plan.tasks if task.task_id not in terminal_task_ids
        ]
        # Drop the AWAITING_APPROVAL placeholder for the task we're about to
        # retry -- it is re-appended below with its real outcome.
        steps = [step for step in existing_steps if step.status != StepStatus.AWAITING_APPROVAL]
        results = [
            result for result in existing_results if result.metadata.get("status") != "awaiting_approval"
        ]
        history = [
            HistoryItem(role=record["role"], content=record["content"])
            for record in self._store.list_messages(session_id, tenant_id=tenant_id)
        ]
        persisted_count = len(history)

        self._acquire_run_lease(tenant_id=tenant_id, run_id=run_id)
        try:
            current_state, paused = self._process_tasks(
                tasks=remaining_tasks,
                run_id=run_id,
                tenant_id=tenant_id,
                mode=mode,
                results=results,
                steps=steps,
                history=history,
                total_count=len(execution_plan.tasks),
                start_index=len(execution_plan.tasks) - len(remaining_tasks) + 1,
            )
        finally:
            self._quota_service.release_run_lease(run_id)

        return self._finalize_plan_run(
            session_id=session_id,
            run_id=run_id,
            tenant_id=tenant_id,
            results=results,
            steps=steps,
            history=history,
            persisted_count=persisted_count,
            current_state=current_state,
            paused=paused,
            total_tasks=len(execution_plan.tasks),
        )

    def resolve_execution_decision(
        self,
        decision_id: str,
        *,
        tenant_id: str,
        decision: str,
        actor: str,
        persist_as_rule: bool = False,
    ) -> PendingDecision:
        """Approve or deny a pending execution-action decision (E14-S3).

        Args:
            decision_id: The decision to resolve.
            tenant_id: Caller's tenant; must match the decision's tenant.
            decision: ``"approve"`` or ``"deny"``.
            actor: Who resolved it.
            persist_as_rule: Hybrid mode's "always" option — additionally
                grants a durable dynamic permission for the decision's
                category/pattern so equivalent future actions auto-allow
                without pausing again. Ignored when ``decision == "deny"``.

        Returns:
            The resolved decision.

        Raises:
            ValueError: If ``decision`` is neither ``"approve"`` nor ``"deny"``.
            backend.execution.decisions.DecisionNotFoundError: If no such
                decision exists for ``tenant_id``.
            backend.execution.decisions.DecisionAlreadyResolvedError: If it
                was already resolved (including a concurrent timeout).
        """
        if decision not in ("approve", "deny"):
            raise ValueError(f"decision must be 'approve' or 'deny', got {decision!r}")
        status = DecisionStatus.APPROVED if decision == "approve" else DecisionStatus.DENIED
        resolved = self._decision_service.resolve(
            decision_id, tenant_id=tenant_id, decision=status, actor=actor
        )
        if persist_as_rule and status is DecisionStatus.APPROVED:
            self._policy_service.grant_dynamic_permission(
                tenant_id,
                PolicyRule(
                    category=resolved.category,
                    effect=PolicyEffect.ALLOW,
                    scope_kind=PolicyScopeKind.PROJECT,
                    scope_id="*",
                    pattern=resolved.pattern,
                ),
                actor=actor,
            )
        return resolved

    def list_pending_execution_decisions(self, *, tenant_id: str) -> List[PendingDecision]:
        """List every still-pending execution-action decision for a tenant."""
        return self._decision_service.list_pending(tenant_id)

    def _find_run_record(
        self, session_id: str, run_id: str, *, tenant_id: str
    ) -> Optional[dict[str, Any]]:
        """Find one run's raw stored record by id, or ``None`` if not found."""
        for record in self._store.list_runs(session_id, tenant_id=tenant_id):
            if record["id"] == run_id:
                return record
        return None

    def _execute_plan_run(
        self,
        *,
        execution_plan: ExecutionPlan,
        session_id: str,
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode = ExecutionMode.AUTO,
    ) -> OrchestratorRun:
        """Execute one already-admitted derived plan and record the run.

        Args:
            execution_plan: The already-derived, non-empty execution plan.
            session_id: Session the plan belongs to.
            run_id: Already-leased run identifier.
            tenant_id: Tenant this run belongs to.
            mode: Execution mode governing task-level pausing (E14-S3).

        Returns:
            The run, completed or paused awaiting a decision.
        """
        self._store.create_run(
            run_id=run_id,
            session_id=session_id,
            status=RunStatus.RUNNING,
            run_type=RunType.PLAN_EXECUTION,
            current_state="starting",
            trigger_message="Execute derived task plan",
            results=[],
            steps=[],
            tenant_id=tenant_id,
        )

        history = [
            HistoryItem(role=record["role"], content=record["content"])
            for record in self._store.list_messages(session_id, tenant_id=tenant_id)
        ]
        persisted_count = len(history)
        results: List[AgentExecution] = []
        steps: List[RunStep] = []

        current_state, paused = self._process_tasks(
            tasks=execution_plan.tasks,
            run_id=run_id,
            tenant_id=tenant_id,
            mode=mode,
            results=results,
            steps=steps,
            history=history,
            total_count=len(execution_plan.tasks),
            start_index=1,
        )

        return self._finalize_plan_run(
            session_id=session_id,
            run_id=run_id,
            tenant_id=tenant_id,
            results=results,
            steps=steps,
            history=history,
            persisted_count=persisted_count,
            current_state=current_state,
            paused=paused,
            total_tasks=len(execution_plan.tasks),
        )

    def _finalize_plan_run(
        self,
        *,
        session_id: str,
        run_id: str,
        tenant_id: str,
        results: List[AgentExecution],
        steps: List[RunStep],
        history: List[HistoryItem],
        persisted_count: int,
        current_state: str,
        paused: bool,
        total_tasks: int,
    ) -> OrchestratorRun:
        """Persist and return the run, completed or paused awaiting a decision.

        Args:
            session_id: Session the run belongs to.
            run_id: Identifier of the run being finalized.
            tenant_id: Tenant the run belongs to.
            results: Agent results accumulated by the run.
            steps: Step records accumulated by the run.
            history: The full conversation, including entries this run added.
            persisted_count: How many of ``history``'s entries were already in
                the store when it was loaded. Everything beyond that is the
                tail handed to :meth:`append_messages` (E44-S4).
            current_state: The run's final flow state.
            paused: Whether the run stopped awaiting a human decision.
            total_tasks: Number of planned tasks in the execution plan.

        Returns:
            The persisted run.
        """
        status = RunStatus.AWAITING_APPROVAL if paused else RunStatus.COMPLETED
        summary = (
            f"Paused after {len(steps)}/{total_tasks} planned tasks, awaiting a decision."
            if paused
            else f"Executing {total_tasks} planned tasks derived from the latest analysis."
        )
        history.append(HistoryItem(role="executor", content=summary))
        ordered_history = self._normalize_execution_history(history)
        self._store.update_run(
            run_id=run_id,
            status=status,
            current_state=current_state,
            results=[
                {
                    "agent": result.agent,
                    "content": result.content,
                    "metadata": dict(result.metadata),
                }
                for result in results
            ],
            steps=[step.to_dict() for step in steps],
            tenant_id=tenant_id,
        )
        self._store.append_messages(
            session_id,
            run_id,
            [item.to_dict() for item in ordered_history[persisted_count:]],
            tenant_id=tenant_id,
        )

        return OrchestratorRun(
            run_id=run_id,
            session_id=session_id,
            status=status,
            run_type=RunType.PLAN_EXECUTION,
            current_state=current_state,
            history=ordered_history,
            results=results,
            steps=steps,
        )


__all__ = ["PlanLifecycleMixin"]
