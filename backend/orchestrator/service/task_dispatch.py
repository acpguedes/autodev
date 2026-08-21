"""Per-batch task dispatch: environment lifecycle, action resolution, and dispatch rendering (E47-S5)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from backend.orchestrator.service import events
from backend.execution.contracts import (
    ExecutionAction,
    ExecutionFailureKind,
    ExecutionResult,
)
from backend.execution.executor import TaskExecutionOutcome
from backend.execution.modes import ExecutionMode
from backend.execution.policy import ACTION_TYPE_TO_POLICY_CATEGORY, DecisionStatus, PendingDecision, match_target
from backend.orchestrator.service._shared import OrchestratorState
from backend.orchestrator.service.environment_scope import ExecutionEnvironmentScope
from backend.orchestrator.service.models import (
    AgentExecution,
    DispatchRecord,
    ExecutionTask,
    HistoryItem,
    RunStep,
    build_timeline_output,
)
from backend.orchestrator.service.task_outcomes import (
    append_task_entry,
    build_awaiting_approval_entry,
    build_dispatched_entry,
)


class TaskDispatchMixin(OrchestratorState):
    """Dispatch one batch of execution-plan tasks, under an isolated E32 environment."""

    def _process_tasks(
        self,
        *,
        tasks: List["ExecutionTask"],
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode,
        results: List[AgentExecution],
        steps: List[RunStep],
        history: List[HistoryItem],
        total_count: int,
        start_index: int,
    ) -> tuple[str, bool]:
        """Process *tasks* in order under *mode*, appending to the given lists in place.

        Stops early (returning ``paused=True``) the moment a task requires
        a still-pending human decision — preserving every already-recorded
        step/result as partial state, strengthening E14-S1's "interrupted
        execution preserves partial state" criterion rather than adding a
        second mechanism for it.

        Provisions one E32 execution environment for this batch (a no-op
        when *tasks* is empty), scopes every dispatched action's runner to
        it, and tears it down -- collecting the batch's declared outputs
        via the artifact store first -- once the batch finishes or pauses,
        all via :class:`~backend.orchestrator.service.environment_scope.ExecutionEnvironmentScope`
        (E47-S5-T1). A provisioning failure (capacity ceiling or backend
        error) denies every task in the batch rather than silently falling
        back to unisolated execution (E32-S3/S4 fail-closed).

        Returns:
            ``(current_state, paused)``.
        """
        current_state = steps[-1].step_key if steps else "starting"
        if not tasks:
            return current_state, False

        scope = ExecutionEnvironmentScope(self._environment_manager, self._composite_runner)
        scope.provision(
            run_id=run_id,
            tenant_id=tenant_id,
            workspace_ref=str((self._project_root or Path(".")).resolve()),
        )

        action_results: List[ExecutionResult] = []
        try:
            dispatch_records: List[DispatchRecord] = []
            for offset, task in enumerate(tasks):
                index = start_index + offset
                started_at = self._timestamp()
                actions = self._task_executor.derive_actions(task)
                outcome, pending = self._resolve_task_actions(
                    task=task,
                    actions=actions,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    mode=mode,
                    environment_denied_reason=scope.denied_reason,
                )
                completed_at = self._timestamp()
                current_state = task.task_id

                if pending is not None:
                    self._render_dispatch_records(
                        dispatch_records,
                        action_results=action_results,
                        run_id=run_id,
                        tenant_id=tenant_id,
                        mode=mode,
                        total_count=total_count,
                        results=results,
                        steps=steps,
                        history=history,
                    )
                    entry = build_awaiting_approval_entry(
                        task=task,
                        index=index,
                        total_count=total_count,
                        pending=pending,
                        started_at=started_at,
                        completed_at=completed_at,
                    )
                    append_task_entry(entry, results=results, steps=steps, history=history)
                    return current_state, True

                assert outcome is not None
                action_results.extend(outcome.results)
                dispatch_records.append(
                    DispatchRecord(
                        display_index=index,
                        task=task,
                        started_at=started_at,
                        completed_at=completed_at,
                        outcome=outcome,
                    )
                )
            self._render_dispatch_records(
                dispatch_records,
                action_results=action_results,
                run_id=run_id,
                tenant_id=tenant_id,
                mode=mode,
                total_count=total_count,
                results=results,
                steps=steps,
                history=history,
            )
            return current_state, False
        finally:
            scope.teardown(action_results)

    def _render_dispatch_records(
        self,
        records: List["DispatchRecord"],
        *,
        action_results: List[ExecutionResult],
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode,
        total_count: int,
        results: List[AgentExecution],
        steps: List[RunStep],
        history: List[HistoryItem],
    ) -> None:
        """Run one batched self-repair pass over *records*, then append their final entries in order.

        Replaces one self-repair call per failed validation task with a
        single batched pass (E46-S3) over every "validation" task in
        *records* that carries agent-declared ``commands`` — the only
        tasks eligible for self-repair (E41-S5). ``action_results`` is
        mutated in place by :meth:`_maybe_batch_self_repair` with any
        additional repair-write/revalidation results, so the caller's
        artifact collection sees them without needing to reconcile which
        results are new.

        Args:
            records: Every task dispatched so far this batch, in the
                order they were dispatched — rendered in that same order
                regardless of which ones went through self-repair.
            action_results: The batch's running list of every dispatched
                result, mutated in place (read by the caller's ``finally``
                block for artifact collection).
        """
        from backend.api.timeline_roles import (  # noqa: PLC0415
            timeline_event_type_for_agent_role,
        )

        candidates = [
            (record.task, record.outcome)
            for record in records
            if record.task.category == "validation" and record.task.commands
        ]
        repaired = (
            self._maybe_batch_self_repair(
                candidates,
                batch_results=action_results,
                run_id=run_id,
                tenant_id=tenant_id,
                mode=mode,
            )
            if candidates
            else {}
        )

        for index, task, started_at, completed_at, first_outcome in records:
            outcome, self_check = repaired.get(task.task_id, (first_outcome, None))
            if self_check is not None:
                events.emit_event(
                    "execution.verification.outcome",
                    tenant_id=tenant_id,
                    partition_key=run_id,
                    data={"taskId": task.task_id, "outcome": self_check},
                    subject={"runId": run_id, "taskId": task.task_id},
                )
            timeline_event_type = timeline_event_type_for_agent_role(task.source_agent)
            if timeline_event_type is not None:
                events.emit_event(
                    timeline_event_type,
                    tenant_id=tenant_id,
                    partition_key=run_id,
                    data={
                        "stepKey": task.task_id,
                        "actorRole": task.source_agent,
                        "status": outcome.status,
                        "output": build_timeline_output(outcome.results),
                    },
                    subject={"runId": run_id, "taskId": task.task_id},
                )
            entry = build_dispatched_entry(
                index=index,
                total_count=total_count,
                task=task,
                started_at=started_at,
                completed_at=completed_at,
                outcome=outcome,
                self_check=self_check,
            )
            append_task_entry(entry, results=results, steps=steps, history=history)

    def _resolve_task_actions(
        self,
        *,
        task: "ExecutionTask",
        actions: List[ExecutionAction],
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode,
        environment_denied_reason: Optional[str] = None,
    ) -> tuple[Optional[TaskExecutionOutcome], Optional[PendingDecision]]:
        """Dispatch *actions* or request a human decision, per *mode*.

        Returns exactly one of ``(outcome, None)`` or ``(None, pending)`` —
        the latter only when a decision is still :attr:`DecisionStatus.PENDING`
        (i.e. genuinely blocking, not yet resolved or self-expired).

        Args:
            environment_denied_reason: When set (E32-S3/S4), this batch's
                execution environment failed to provision; every action is
                denied without dispatching, regardless of mode.
        """
        if environment_denied_reason is not None and actions:
            return (
                self._task_executor.deny_all(
                    actions,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    reason=environment_denied_reason,
                    failure_kind=ExecutionFailureKind.ENVIRONMENT_UNAVAILABLE,
                ),
                None,
            )
        if not actions or mode is ExecutionMode.AUTO:
            return self._task_executor.dispatch(actions, run_id=run_id, tenant_id=tenant_id), None

        needs_decision = mode is ExecutionMode.APPROVAL or (
            mode is ExecutionMode.HYBRID
            and any(
                not self._policy_service.preview(tenant_id=tenant_id, action=action).matched
                for action in actions
            )
        )
        if not needs_decision:
            return self._task_executor.dispatch(actions, run_id=run_id, tenant_id=tenant_id), None

        primary = actions[0]
        category = ACTION_TYPE_TO_POLICY_CATEGORY[primary.type]
        pending = self._decision_service.request(
            tenant_id=tenant_id,
            run_id=run_id,
            task_id=task.task_id,
            action=primary,
            category=category,
            prompt=f"Approve {primary.type.value} for task {task.title!r}?",
            pattern=match_target(primary),
        )
        if pending.status is DecisionStatus.PENDING:
            return None, pending
        if pending.status is DecisionStatus.APPROVED:
            outcome = self._task_executor.dispatch(
                actions,
                run_id=run_id,
                tenant_id=tenant_id,
                pre_approved_action_ids=frozenset(action.action_id for action in actions),
            )
            return outcome, None
        reason = (
            "human denied this action"
            if pending.status is DecisionStatus.DENIED
            else "decision timed out (deny-and-stop fallback)"
        )
        outcome = self._task_executor.deny_all(
            actions, run_id=run_id, tenant_id=tenant_id, reason=reason
        )
        return outcome, None


__all__ = ["TaskDispatchMixin"]
