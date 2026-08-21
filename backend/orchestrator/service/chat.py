"""Session creation and the per-message chat-graph run (E47-S5)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.agents import AgentContext, PlannerAgent
from backend.jobs.queue import get_queue
from backend.observability.tracing import trace_run
from backend.orchestrator.service import events
from backend.orchestrator.service._shared import OrchestratorState
from backend.orchestrator.service.models import (
    AgentGraphState,
    HistoryItem,
    OrchestratorRun,
    PlanSession,
    PreparedRun,
    RunStatus,
    RunType,
)
from backend.persistence.tenancy import DEFAULT_TENANT_ID

#: Job type for :meth:`ChatMixin.begin_message`'s background graph run (E43-S6).
#: Owned here (the enqueuing side) so this module has no dependency on
#: ``message_job`` -- ``message_job._run_message_job`` imports this constant
#: from here instead, avoiding an import cycle through ``core``.
MESSAGE_RUN_JOB_TYPE = "orchestrator.message_run"


class ChatMixin(OrchestratorState):
    """Plan-session creation and the message-driven agent-graph run."""

    def create_plan(self, goal: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> PlanSession:
        """Create a new session and generate its initial plan via the planner agent.

        Args:
            goal: High-level goal driving the session.
            tenant_id: Tenant the new session belongs to. Callers behind
                authentication must pass the resolved principal's tenant —
                never a client-supplied value.

        Returns:
            The newly created planning session.
        """
        planner: PlannerAgent = self._require_agent("planner")  # type: ignore[assignment]
        session_id = str(uuid4())
        context = AgentContext(session_id=session_id, goal=goal, user_request=goal)
        plan_result = planner.run(context)
        plan_steps = self._extract_plan_steps(plan_result)
        status = RunStatus.AWAITING_INPUT

        self._store.create_session(
            session_id=session_id,
            goal=goal,
            plan=plan_steps,
            artifacts={planner.name: dict(plan_result.metadata)},
            tenant_id=tenant_id,
        )

        return PlanSession(
            session_id=session_id, goal=goal, plan=plan_steps, status=status
        )

    def _prepare_run(
        self, session_id: str, message: str, *, tenant_id: str
    ) -> "PreparedRun":
        """Validate the session, admit the run, and persist its initial row.

        Shared setup for :meth:`handle_message` (runs the graph inline) and
        :meth:`begin_message` (E43-S6: runs the graph in a background job so
        the run_id reaches the caller before the graph does) — both need the
        exact same session lookup, run-type inference, lease acquisition, and
        initial ``RunStatus.RUNNING`` row before diverging on how the graph
        itself gets invoked.

        Args:
            session_id: Identifier of the session to continue.
            message: User message to process.
            tenant_id: Tenant the session must belong to.

        Returns:
            The prepared run's session record, run id, run type, and flow id.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
            QuotaExceededError: If the tenant is at its concurrent-run limit.
        """
        session_record = self._store.get_session(session_id, tenant_id=tenant_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")

        run_type = self._infer_run_type(goal=session_record["goal"], message=message)
        run_id = str(uuid4())
        self._acquire_run_lease(tenant_id=tenant_id, run_id=run_id)
        self._store.create_run(
            run_id=run_id,
            session_id=session_id,
            status=RunStatus.RUNNING,
            run_type=run_type,
            current_state="starting",
            trigger_message=message,
            results=[],
            steps=[],
            tenant_id=tenant_id,
        )
        flow_id = f"orchestrator.{run_type}"
        # Emitted here (synchronously, before returning) rather than at the
        # top of _execute_message_run: this event is what creates the run's
        # EventStore projection (backend/events/store.py's append ->
        # _upsert_projection), which /v2/runs/{id}/events/stream's existence
        # check (backend/api/routers/runs_stream_v2.py) requires. Since
        # E43-S6's begin_message defers _execute_message_run to a background
        # job, leaving this emit there would race the caller opening that
        # stream immediately after begin_message returns -- a real,
        # intermittent 404, not just a test timing artifact.
        events.emit_event(
            "flow.run.started",
            tenant_id=tenant_id,
            partition_key=run_id,
            data={"flowId": flow_id, "flowVersion": "1.0.0"},
            subject={"runId": run_id, "sessionId": session_id},
        )
        return PreparedRun(
            session_record=session_record,
            run_id=run_id,
            run_type=run_type,
            flow_id=flow_id,
        )

    def handle_message(
        self, session_id: str, message: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> OrchestratorRun:
        """Run the agent graph for a new message in an existing session.

        Args:
            session_id: Identifier of the session to continue.
            message: User message to process.
            tenant_id: Tenant the session must belong to. Callers behind
                authentication must pass the resolved principal's tenant —
                never a client-supplied value. A session belonging to a
                different tenant is treated exactly like an unknown one.

        Returns:
            The completed orchestration run.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        prepared = self._prepare_run(session_id, message, tenant_id=tenant_id)
        try:
            with trace_run(
                run_id=prepared.run_id,
                tenant_id=tenant_id,
                flow_id=prepared.flow_id,
            ) as run_trace:
                result = self._execute_message_run(
                    session_record=prepared.session_record,
                    session_id=session_id,
                    message=message,
                    run_id=prepared.run_id,
                    run_type=prepared.run_type,
                    flow_id=prepared.flow_id,
                    tenant_id=tenant_id,
                )
                run_trace.finish(status="completed")
                return result
        finally:
            self._quota_service.release_run_lease(prepared.run_id)

    def begin_message(
        self, session_id: str, message: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> OrchestratorRun:
        """Start a new message's agent graph in the background and return immediately (E43-S6).

        Unlike :meth:`handle_message`, this returns as soon as the run is
        admitted and its row persisted -- before the (potentially
        multi-minute, multi-agent) graph runs -- so the caller has a
        ``run_id`` to open a live ``run.timeline.*``/``execution.action.*``
        event-stream subscription against while the run is still in
        progress, instead of only after it has already finished. The graph
        itself, and every event it emits mid-run, are unchanged; only when
        the caller learns the run_id changes.

        Args:
            session_id: Identifier of the session to continue.
            message: User message to process.
            tenant_id: Tenant the session must belong to.

        Returns:
            An :class:`~backend.orchestrator.service.models.OrchestratorRun`
            reflecting the just-created, still-``running`` state (empty
            ``history``/``results``/``steps``) -- poll :meth:`get_run`/
            ``GET /v2/turns/{id}`` for the real, completed result.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
            QuotaExceededError: If the tenant is at its concurrent-run limit.
        """
        prepared = self._prepare_run(session_id, message, tenant_id=tenant_id)
        get_queue().enqueue(
            MESSAGE_RUN_JOB_TYPE,
            {
                "session_id": session_id,
                "message": message,
                "run_id": prepared.run_id,
                "run_type": prepared.run_type.value,
                "flow_id": prepared.flow_id,
                "tenant_id": tenant_id,
            },
        )
        return OrchestratorRun(
            run_id=prepared.run_id,
            session_id=session_id,
            status=RunStatus.RUNNING,
            run_type=prepared.run_type,
            current_state="starting",
            history=[],
            results=[],
            steps=[],
        )

    def _execute_message_run(
        self,
        *,
        session_record: dict[str, Any],
        session_id: str,
        message: str,
        run_id: str,
        run_type: RunType,
        flow_id: str,
        tenant_id: str,
        finalize: bool = True,
    ) -> OrchestratorRun:
        """Execute and durably persist one already-created orchestration run.

        Args:
            session_record: Persisted session state used to build agent context.
            session_id: Session being continued.
            message: User message driving the run.
            run_id: Already-persisted run identifier.
            run_type: Explicit workflow category selected for the message.
            flow_id: Stable observability flow identifier.
            tenant_id: Tenant this run belongs to.
            finalize: Whether to persist this run's row as ``RunStatus.COMPLETED``
                and emit ``flow.run.completed`` (E43-S8). Callers that chain
                real task dispatch onto the same run_id afterward (E43-S8's
                auto-execute) pass ``False`` -- persisting ``COMPLETED`` here
                only to immediately reopen it would leave a real, if narrow,
                race window where a poller can observe a premature
                "completed" status and stop watching before the chained
                dispatch (which can take much longer) ever starts.

        Returns:
            The orchestration run reflecting this conversation's real
            results/steps -- already durably persisted as ``COMPLETED``
            when ``finalize`` is true; otherwise the caller is responsible
            for persisting the run's real final state.
        """
        history = [
            HistoryItem(role=record["role"], content=record["content"])
            for record in self._store.list_messages(session_id, tenant_id=tenant_id)
        ]
        user_entry = HistoryItem(role="user", content=message)
        context = AgentContext(
            session_id=session_id,
            goal=session_record["goal"],
            user_request=message,
            history=[item.to_dict() for item in history] + [user_entry.to_dict()],
            artifacts=dict(session_record["artifacts"] or {}),
        )
        initial_state: AgentGraphState = {
            "context": context,
            "results": [],
            "steps": [],
            "current_state": "starting",
            "run_id": run_id,
            "tenant_id": tenant_id,
        }
        final_state = self._graph.invoke(initial_state)
        final_context = final_state["context"]
        results = list(final_state["results"])
        steps = list(final_state["steps"])
        current_state = final_state["current_state"]
        next_history = [HistoryItem(**item) for item in final_context.history]
        # Only what this run added: everything up to ``len(history)`` is
        # already persisted, and the store now appends exactly what it is
        # given rather than re-reading the conversation to find the tail
        # itself (E44-S4).
        self._store.append_messages(
            session_id,
            run_id,
            [item.to_dict() for item in next_history[len(history) :]],
            tenant_id=tenant_id,
        )
        self._store.update_session_artifacts(
            session_id,
            self._clone_artifacts(final_context.artifacts),
            tenant_id=tenant_id,
        )
        if finalize:
            self._store.update_run(
                run_id=run_id,
                status=RunStatus.COMPLETED,
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
            events.emit_event(
                "flow.run.completed",
                tenant_id=tenant_id,
                partition_key=run_id,
                data={"status": "completed", "costUsd": 0.0, "tokens": 0},
                subject={"runId": run_id, "sessionId": session_id},
            )
        return OrchestratorRun(
            run_id=run_id,
            session_id=session_id,
            status=RunStatus.COMPLETED,
            run_type=run_type,
            current_state=current_state,
            history=next_history,
            results=results,
            steps=steps,
        )

    def get_plan(self, session_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> PlanSession:
        """Fetch a session's plan.

        Args:
            session_id: Identifier of the session.
            tenant_id: Tenant the session must belong to.

        Returns:
            The session's plan.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        state = self._store.get_session(session_id, tenant_id=tenant_id)
        if state is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return PlanSession(
            session_id=state["id"],
            goal=state["goal"],
            plan=list(state["plan"] or []),
            status=RunStatus.AWAITING_INPUT,
        )


__all__ = ["ChatMixin", "MESSAGE_RUN_JOB_TYPE"]
