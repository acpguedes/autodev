"""Typed per-task processing outcome for the plan-execution dispatch loop (E47-S5-T2).

``_process_tasks`` used to append to its ``results``/``steps``/``history``
lists inline at two separate places -- once for a task that paused awaiting a
human decision, once per dispatched task rendered by
``task_dispatch._render_dispatch_records`` -- each hand-building the same
three-way (:class:`~backend.orchestrator.service.models.AgentExecution`,
:class:`~backend.orchestrator.service.models.RunStep`,
:class:`~backend.orchestrator.service.models.HistoryItem`) triple. Both call
sites now build a :class:`TaskAppendEntry` and hand it to
:func:`append_task_entry`, the single place any of those three lists is
mutated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.execution.executor import TaskExecutionOutcome
from backend.execution.policy import PendingDecision
from backend.orchestrator.service.models import (
    AgentExecution,
    ExecutionTask,
    HistoryItem,
    RunStep,
    StepStatus,
)


@dataclass(slots=True)
class TaskAppendEntry:
    """One task's rendered (result, step, history) triple, ready to append."""

    result: AgentExecution
    step: RunStep
    history: HistoryItem


def append_task_entry(
    entry: TaskAppendEntry,
    *,
    results: List[AgentExecution],
    steps: List[RunStep],
    history: List[HistoryItem],
) -> None:
    """Append one task's rendered entry to the run's accumulating lists, in lockstep."""
    results.append(entry.result)
    steps.append(entry.step)
    history.append(entry.history)


def build_awaiting_approval_entry(
    *,
    task: ExecutionTask,
    index: int,
    total_count: int,
    pending: PendingDecision,
    started_at: str,
    completed_at: str,
) -> TaskAppendEntry:
    """Build the entry recording a task paused awaiting a human decision."""
    return TaskAppendEntry(
        result=AgentExecution(
            agent="executor",
            content=f"[{index}/{total_count}] {task.title} — awaiting a decision",
            metadata={
                "task_id": task.task_id,
                "title": task.title,
                "description": task.description,
                "source_agent": task.source_agent,
                "category": task.category,
                "status": "awaiting_approval",
                "decision_id": pending.decision_id,
                "actions": [],
            },
        ),
        step=RunStep(
            step_key=task.task_id,
            agent=task.source_agent,
            status=StepStatus.AWAITING_APPROVAL,
            started_at=started_at,
            completed_at=completed_at,
        ),
        history=HistoryItem(
            role="executor",
            content=f"Paused task {index}: {task.title} awaiting a decision.",
        ),
    )


def build_dispatched_entry(
    *,
    index: int,
    total_count: int,
    task: ExecutionTask,
    started_at: str,
    completed_at: str,
    outcome: TaskExecutionOutcome,
    self_check: Optional[str],
) -> TaskAppendEntry:
    """Build the entry recording one dispatched (and possibly self-repaired) task."""
    step_status = StepStatus.COMPLETED if outcome.status == "completed" else StepStatus.FAILED
    execution_metadata: Dict[str, Any] = {
        "task_id": task.task_id,
        "title": task.title,
        "description": task.description,
        "source_agent": task.source_agent,
        "category": task.category,
        "status": outcome.status,
        "actions": [result.to_dict() for result in outcome.results],
    }
    if self_check is not None:
        execution_metadata["self_check"] = self_check
    return TaskAppendEntry(
        result=AgentExecution(
            agent="executor",
            content=f"[{index}/{total_count}] {task.title}",
            metadata=execution_metadata,
        ),
        step=RunStep(
            step_key=task.task_id,
            agent=task.source_agent,
            status=step_status,
            started_at=started_at,
            completed_at=completed_at,
        ),
        history=HistoryItem(
            role="executor",
            content=(
                f"{'Completed' if step_status == StepStatus.COMPLETED else 'Failed'} "
                f"task {index}: {task.title} ({task.category})."
            ),
        ),
    )


__all__ = [
    "TaskAppendEntry",
    "append_task_entry",
    "build_awaiting_approval_entry",
    "build_dispatched_entry",
]
