"""Background job pathway for a message-driven run (E43-S6, E47-S5-T4).

Owns the two pieces every ``/v2`` request-scoped caller and the background
job handler need to construct and run an :class:`OrchestratorService`
outside of ``chat.begin_message`` itself: :func:`build_default_orchestrator`
and the job handler it enqueues into.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from backend.config.runtime import get_runtime_config_service
from backend.config.settings import get_settings
from backend.orchestrator.service import events
from backend.execution.modes import ExecutionMode
from backend.jobs.queue import register_handler
from backend.observability.tracing import trace_run
from backend.orchestrator.service.chat import MESSAGE_RUN_JOB_TYPE
from backend.orchestrator.service.core import OrchestratorConfig, OrchestratorService
from backend.orchestrator.service.models import HistoryItem, RunStatus, RunType


def build_default_orchestrator() -> "OrchestratorService":
    """Build an :class:`OrchestratorService` bound to the current runtime config.

    The one construction every ``/v2`` request-scoped caller and this
    module's background job handler both need -- a fresh instance (matching
    the "constructed fresh per request/job, state lives in the shared
    durable store" convention already used throughout ``/v2`` routers)
    pointed at whatever project root the runtime config currently resolves
    to.

    Returns:
        A new :class:`OrchestratorService`.
    """
    config_service = get_runtime_config_service()
    runtime_config = config_service.apply_to_environment()
    return OrchestratorService(
        config=OrchestratorConfig(), project_root=Path(runtime_config.repository.project_root)
    )


@register_handler(MESSAGE_RUN_JOB_TYPE)
def _run_message_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run one message's agent graph in the background and persist its outcome.

    Registered in this module, which is the only thing that enqueues this
    job type (``chat.ChatMixin.begin_message``) -- guarantees this handler
    is registered before anything can try to enqueue it, the same pattern
    :mod:`backend.repository.indexing` already uses for its own job type.

    On success, persists the same ``RunStatus.COMPLETED`` row
    :meth:`~backend.orchestrator.service.chat.ChatMixin._execute_message_run`
    always has -- unless ``Settings().autodev_chat_auto_execute`` is on and
    the conversation derived at least one executable task (E43-S8), in
    which case this continues, on the *same* run_id/run row, straight into
    the same task-dispatch path "Run plan" uses
    (:meth:`~backend.orchestrator.service.task_dispatch.TaskDispatchMixin._process_tasks`
    + :meth:`~backend.orchestrator.service.plan_lifecycle.PlanLifecycleMixin._finalize_plan_run`)
    before persisting the real final status -- so real command/file-write
    output keeps streaming on the same live subscription the conversation
    was already using, with no second click and no new run_id for the
    frontend to hand off to. On any exception, persists ``RunStatus.FAILED``
    with the error recorded as a synthetic result entry instead of leaving
    the row stuck at ``running`` forever (the failure mode
    :meth:`~backend.orchestrator.service.chat.ChatMixin.handle_message` has
    always had, silent because it previously always had an HTTP caller to
    surface a 500 to instead).

    Args:
        payload: ``session_id``, ``message``, ``run_id``, ``run_type``
            (a :class:`RunType` value string), ``flow_id``, ``tenant_id`` --
            exactly what
            :meth:`~backend.orchestrator.service.chat.ChatMixin.begin_message`
            enqueues.

    Returns:
        ``{"run_id": ...}``, for the job queue's own status record; the
        durably persisted run row is the result callers actually care about.
    """
    orchestrator = build_default_orchestrator()
    run_id = payload["run_id"]
    tenant_id = payload["tenant_id"]
    session_id = payload["session_id"]
    flow_id = payload["flow_id"]
    try:
        with trace_run(run_id=run_id, tenant_id=tenant_id, flow_id=flow_id) as run_trace:
            session_record = orchestrator._store.get_session(session_id, tenant_id=tenant_id)
            if session_record is None:
                raise KeyError(f"Unknown session_id: {session_id}")
            auto_execute = get_settings().autodev_chat_auto_execute
            chat_run = orchestrator._execute_message_run(
                session_record=session_record,
                session_id=session_id,
                message=payload["message"],
                run_id=run_id,
                run_type=RunType(payload["run_type"]),
                flow_id=flow_id,
                tenant_id=tenant_id,
                finalize=not auto_execute,
            )
            if auto_execute:
                execution_plan = orchestrator.build_execution_plan(session_id, tenant_id=tenant_id)
                if execution_plan.tasks:
                    results = list(chat_run.results)
                    steps = list(chat_run.steps)
                    history = [
                        HistoryItem(role=record["role"], content=record["content"])
                        for record in orchestrator._store.list_messages(session_id, tenant_id=tenant_id)
                    ]
                    persisted_count = len(history)
                    current_state, paused = orchestrator._process_tasks(
                        tasks=execution_plan.tasks,
                        run_id=run_id,
                        tenant_id=tenant_id,
                        mode=ExecutionMode.AUTO,
                        results=results,
                        steps=steps,
                        history=history,
                        total_count=len(execution_plan.tasks),
                        start_index=1,
                    )
                    orchestrator._finalize_plan_run(
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
                else:
                    # Auto-execute is on but this turn derived no executable
                    # tasks (e.g. a question, not a change request) --
                    # _execute_message_run was called with finalize=False and
                    # so never persisted its own completion; do it here.
                    orchestrator._store.update_run(
                        run_id=run_id,
                        status=RunStatus.COMPLETED,
                        current_state=chat_run.current_state,
                        results=[
                            {"agent": result.agent, "content": result.content, "metadata": dict(result.metadata)}
                            for result in chat_run.results
                        ],
                        steps=[step.to_dict() for step in chat_run.steps],
                        tenant_id=tenant_id,
                    )
                    events.emit_event(
                        "flow.run.completed",
                        tenant_id=tenant_id,
                        partition_key=run_id,
                        data={"status": "completed", "costUsd": 0.0, "tokens": 0},
                        subject={"runId": run_id, "sessionId": session_id},
                    )
            run_trace.finish(status="completed")
    except Exception as exc:  # noqa: BLE001 - any agent/graph failure must still resolve the run
        orchestrator._store.update_run(
            run_id=run_id,
            status=RunStatus.FAILED,
            current_state="failed",
            results=[{"agent": "system", "content": str(exc), "metadata": {"error": True}}],
            steps=[],
            tenant_id=tenant_id,
        )
    finally:
        orchestrator._quota_service.release_run_lease(run_id)
    return {"run_id": run_id}


__all__ = ["build_default_orchestrator"]
