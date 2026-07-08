"""The Flow Engine: executes declarative flow graphs with durable state.

E3-S2 scope: walk the graph from the entry node, render each node's input
bindings against run state, execute the node through its registered handler,
persist every Run/Step transition, enforce fail-closed run budgets, and emit
ordered lifecycle events (``flow.run.started``, ``run.step.started``,
``run.step.completed``, ``run.step.failed``, ``flow.run.completed``,
``flow.run.failed``) into the durable event store.

E3-S3 adds per-step checkpoints as the recovery contract (the state persisted
after every step is the checkpoint), retry/backoff per the manifest retry
policy, crash recovery through :meth:`FlowEngine.resume_run`
(``flow.run.resumed``), and deterministic replay through
:meth:`FlowEngine.replay_run` (``flow.run.replayed``) under the ADR-005
determinism boundary.

E3-S4 adds human-in-the-loop pauses: a ``human`` node stops the loop as
``waiting_human`` (with ``flow.run.paused``) until :mod:`backend.flows.human`
resumes the run.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from backend.flows.activation import NodeActivationMixin
from backend.flows.budgets import (
    budget_cap_document,
    budget_violation,
    effective_budgets,
)
from backend.flows.checkpoint import (
    FlowReplayReport,
    build_eval_state,
    final_output,
    replay_decision_path,
    select_next_node,
)
from backend.events.runtime import emit_event
from backend.flows.expressions import ExpressionError
from backend.flows.handlers import FlowHandlerRegistry, FlowNodeError, build_default_handlers
from backend.flows.manifest import validate_run_input
from backend.flows.model import FlowBudgets
from backend.flows.records import TERMINAL_RUN_STATUSES
from backend.flows.registry import FlowRegistry
from backend.flows.state import FlowRunRecord, FlowRunStore
from backend.persistence.database import get_store


class FlowRunError(RuntimeError):
    """Raised when a run cannot be started (unknown flow, invalid input)."""


class FlowEngine(NodeActivationMixin):
    """Executes registered flows with durable, observable Run/Step state."""

    def __init__(
        self,
        *,
        store: Any | None = None,
        registry: FlowRegistry | None = None,
        run_store: FlowRunStore | None = None,
        handlers: FlowHandlerRegistry | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
        now: Callable[[], datetime] | None = None,
        max_steps_per_run: int = 1000,
    ) -> None:
        """Initialize the engine and its collaborators.

        Args:
            store: Durable store shared by the registry and run store;
                defaults to the process-wide store.
            registry: Flow definition registry; created on the store when
                omitted.
            run_store: Run/Step/Event store; created on the store when omitted.
            handlers: Node handler registry; defaults from
                :func:`backend.flows.handlers.build_default_handlers`.
            clock: Monotonic clock used for wall-clock budget enforcement;
                defaults to :func:`time.monotonic`.
            sleeper: Blocking sleep used for retry backoff between node
                attempts; defaults to :func:`time.sleep` (injectable so
                tests do not wait).
            now: Wall-clock source used for human-wait expiry timestamps
                (E3-S4); defaults to timezone-aware ``datetime.now(utc)``.
            max_steps_per_run: Engine safety cap on node activations per run
                (fails closed); complements, and never replaces, manifest
                budgets.
        """
        self._store = store or get_store()
        self.registry = registry or FlowRegistry(self._store)
        self.runs = run_store or FlowRunStore(self._store)
        self.handlers = handlers or build_default_handlers(store=self._store)
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self.now: Callable[[], datetime] = now or (
            lambda: datetime.now(timezone.utc)
        )
        self._max_steps = max_steps_per_run

    # ------------------------------------------------------------------ API

    def start_run(
        self,
        flow_id: str,
        *,
        version_range: str = "*",
        input: dict[str, Any] | None = None,
        trigger: dict[str, Any] | None = None,
        tenant_id: str = "default",
        parent_run_id: str | None = None,
        execute: bool = True,
        budget_cap: FlowBudgets | None = None,
    ) -> FlowRunRecord:
        """Create a run for a registered flow and (by default) execute it.

        Args:
            flow_id: Fully qualified flow id.
            version_range: SemVer range used to resolve the flow version.
            input: Run input payload, validated against the flow's declared
                input schema (required properties).
            trigger: Normalized trigger document; defaults to ``{"type": "api"}``.
            tenant_id: Tenant the run is scoped to.
            parent_run_id: Id of the parent run for sub-flow runs.
            execute: Whether to execute the graph synchronously.
            budget_cap: Optional cap on the run's budgets; the engine enforces
                the element-wise minimum of the manifest budgets and this cap
                (ADR-006 budget propagation). Persisted in the run state so
                resumed executions keep the same limits.

        Returns:
            The resulting run record (terminal when ``execute`` is ``True``).

        Raises:
            FlowRunError: If the flow is unknown or the input is invalid.
        """
        try:
            manifest = self.registry.resolve(flow_id, version_range)
        except KeyError as exc:
            raise FlowRunError(str(exc)) from exc
        run_input = dict(input or {})
        input_errors = validate_run_input(manifest, run_input)
        if input_errors:
            raise FlowRunError("; ".join(input_errors))

        entry_id = manifest.entry_node().id
        state: dict[str, Any] = {
            "cursor": entry_id,
            "nodes": {},
            "metrics": {"tokens": 0.0, "cost_usd": 0.0},
        }
        if budget_cap is not None:
            state["budget_cap"] = budget_cap_document(budget_cap)
        run = self.runs.create_run(
            flow_id=manifest.id,
            flow_version=manifest.version,
            tenant_id=tenant_id,
            trigger=dict(trigger or {"type": "api"}),
            input=run_input,
            state=state,
            parent_run_id=parent_run_id,
        )
        self.runs.append_event(
            run_id=run.run_id,
            name="flow.run.started",
            payload={
                "flowId": manifest.id,
                "flowVersion": manifest.version,
                "tenantId": tenant_id,
                "trigger": run.trigger,
                "entryNodeId": entry_id,
            },
        )
        emit_event(
            "flow.run.started",
            tenant_id=tenant_id,
            partition_key=run.run_id,
            data={"flowId": manifest.id, "flowVersion": manifest.version},
            subject={"runId": run.run_id},
        )
        if execute:
            return self.execute_run(run.run_id)
        return run

    def execute_run(
        self, run_id: str, *, budget_cap: FlowBudgets | None = None
    ) -> FlowRunRecord:
        """Execute a run from its persisted cursor until it stops.

        Executing an already-terminal run is idempotent: the persisted
        terminal record is returned unchanged, without re-executing anything
        (documented E3-S3 decision — safe for API retries). The budgets
        enforced are the element-wise minimum of the manifest budgets, any
        cap persisted in the run state at start time, and the optional
        ``budget_cap`` argument (ADR-006). They are checked between
        activations and once more before completing, so a run can never
        finish ``completed`` while over budget.

        Args:
            run_id: Id of the run to execute.
            budget_cap: Optional additional cap on the run's budgets.

        Returns:
            The terminal (or paused) run record.

        Raises:
            FlowRunError: If the run or its flow definition is unknown.
        """
        run = self.runs.get_run(run_id)
        if run is None:
            raise FlowRunError(f"unknown run {run_id!r}")
        if run.status in TERMINAL_RUN_STATUSES:
            return run
        return self._run_loop(run, budget_cap=budget_cap)

    def resume_run(self, run_id: str) -> FlowRunRecord:
        """Resume an interrupted run from its last persisted checkpoint.

        A run whose process died mid-execution is left ``running`` (or
        ``pending``) with the cursor and every completed node output already
        checkpointed in ``state_json``. Resuming emits ``flow.run.resumed``,
        marks any step still ``running`` (orphaned by the crash) as failed,
        and continues the graph walk from the cursor — completed steps are
        never re-executed because their outputs are already in
        ``state.nodes``.

        Args:
            run_id: Id of the interrupted run.

        Returns:
            The terminal (or paused) run record.

        Raises:
            FlowRunError: If the run is unknown or already terminal.
        """
        run = self.runs.get_run(run_id)
        if run is None:
            raise FlowRunError(f"unknown run {run_id!r}")
        if run.status in TERMINAL_RUN_STATUSES:
            raise FlowRunError(
                f"run {run_id!r} is terminal ({run.status}) and cannot be "
                "resumed; use replay_run for post-mortem verification"
            )
        for step in self.runs.list_steps(run_id):
            if step.status == "running":
                self.runs.complete_step(
                    step.step_id,
                    status="failed",
                    error="interrupted: attempt superseded by resume",
                )
        run = self._reconcile_crash_window(run)
        if run.status in TERMINAL_RUN_STATUSES:
            return run
        self.runs.append_event(
            run_id=run_id,
            name="flow.run.resumed",
            payload={
                "flowId": run.flow_id,
                "flowVersion": run.flow_version,
                "cursor": run.state.get("cursor"),
            },
        )
        return self._run_loop(run)

    def replay_run(self, run_id: str) -> FlowReplayReport:
        """Verify a terminal run's decision path from persisted state alone.

        Node outputs are recorded effects and are never re-executed (LLM,
        tool, and agent calls stay recorded); replay folds them in activation
        order and re-derives every input-binding rendering and routing
        decision as pure functions of the rebuilt state (ADR-005), comparing
        the derived node sequence with the recorded one. The outcome is
        emitted as ``flow.run.replayed``.

        Args:
            run_id: Id of the terminal run to replay.

        Returns:
            A :class:`FlowReplayReport` with ``deterministic``, both node
            sequences, and any divergence detail.

        Raises:
            FlowRunError: If the run is unknown or not terminal.
        """
        run = self.runs.get_run(run_id)
        if run is None:
            raise FlowRunError(f"unknown run {run_id!r}")
        if run.status not in TERMINAL_RUN_STATUSES:
            raise FlowRunError(
                f"run {run_id!r} is not terminal (status {run.status!r}); "
                "only terminal runs can be replayed"
            )
        manifest = self.registry.resolve(run.flow_id, run.flow_version)
        steps = self.runs.list_steps(run_id)
        report = replay_decision_path(manifest, run, steps)
        self.runs.append_event(
            run_id=run_id, name="flow.run.replayed", payload=report.to_document()
        )
        return report

    def _reconcile_crash_window(self, run: FlowRunRecord) -> FlowRunRecord:
        """Fold a committed-but-unrouted step back into the run state.

        ``complete_step`` and the state checkpoint are separate commits; a
        crash between them leaves the cursor node with a *completed* step
        whose output never reached ``state.nodes`` and whose
        ``run.step.completed`` event was never appended. Resuming without
        reconciliation would re-execute that node — re-firing its side
        effects — so the recorded output is folded in, routing is re-derived,
        and the missing event is emitted (flagged ``reconciled``) before the
        walk continues. Legitimate revisits of the cursor node (guarded
        loops) are recognized by their already-appended completion event and
        left untouched. Step metrics lost inside the window are not
        re-charged.

        Args:
            run: The non-terminal run being resumed.

        Returns:
            The (possibly updated) run record; a terminal record when
            re-derived routing fails closed.
        """
        cursor = run.state.get("cursor")
        if not cursor:
            return run
        completed = [
            step
            for step in self.runs.list_steps(run.run_id)
            if step.node_id == cursor and step.status == "completed"
        ]
        if not completed:
            return run
        last = completed[-1]
        routed_step_ids = {
            event.payload.get("stepId")
            for event in self.runs.list_events(run.run_id)
            if event.name == "run.step.completed"
        }
        if last.step_id in routed_step_ids:
            return run
        manifest = self.registry.resolve(run.flow_id, run.flow_version)
        node = manifest.node(str(cursor))
        state = dict(run.state)
        nodes_state = dict(state.get("nodes", {}))
        nodes_state[node.id] = {"output": last.output}
        state["nodes"] = nodes_state
        try:
            next_node = select_next_node(
                manifest, node, build_eval_state(run.input, nodes_state)
            )
        except ExpressionError as exc:
            return self._fail_run(
                run.run_id, state, "predicate_error",
                f"routing after node {node.id!r}: {exc}",
            )
        except FlowNodeError as exc:
            return self._fail_run(run.run_id, state, "no_route", str(exc))
        state["cursor"] = next_node
        self.runs.update_run(run.run_id, state=state)
        self.runs.append_event(
            run_id=run.run_id,
            name="run.step.completed",
            payload={
                "nodeId": node.id,
                "stepId": last.step_id,
                "attempt": last.attempt,
                "nextNodeId": next_node,
                "reconciled": True,
            },
        )
        record = self.runs.get_run(run.run_id)
        if record is None:  # pragma: no cover - the run was just persisted
            raise FlowRunError(f"run {run.run_id!r} vanished while reconciling")
        return record

    # ------------------------------------------------------------- internals

    def _run_loop(
        self, run: FlowRunRecord, *, budget_cap: FlowBudgets | None = None
    ) -> FlowRunRecord:
        """Drive a run from its persisted cursor to a stop condition.

        Shared by :meth:`execute_run` and :meth:`resume_run`: both walk the
        graph from ``state.cursor``, checkpointing state after every step.
        A ``None`` cursor with pending completion (e.g. a crash between the
        last checkpoint and run finalization) falls through to completion
        without re-executing any node.

        Args:
            run: The non-terminal run to drive.
            budget_cap: Optional additional cap on the run's budgets,
                combined with the manifest budgets and any cap persisted in
                the run state (ADR-006).

        Returns:
            The terminal (or paused) run record.
        """
        manifest = self.registry.resolve(run.flow_id, run.flow_version)
        self.runs.update_run(run.run_id, status="running")

        state = dict(run.state)
        state.setdefault("cursor", manifest.entry_node().id)
        state.setdefault("nodes", {})
        state.setdefault("metrics", {"tokens": 0.0, "cost_usd": 0.0})
        budgets = effective_budgets(manifest.budgets, state, budget_cap)
        started = self._clock()
        deadline = started + budgets.max_wall_clock_sec
        activations = 0

        while state.get("cursor"):
            budget_error = budget_violation(
                budgets, state, self._clock() - started, activations, self._max_steps
            )
            if budget_error is not None:
                return self._fail_run(run.run_id, state, "budget_exhausted", budget_error)

            node = manifest.node(str(state["cursor"]))
            outcome_record = self._activate_node(
                run, manifest, node, state, budgets=budgets, deadline=deadline
            )
            if outcome_record is not None:
                return outcome_record
            activations += 1

        budget_error = budget_violation(
            budgets, state, self._clock() - started, 0, self._max_steps
        )
        if budget_error is not None:
            return self._fail_run(run.run_id, state, "budget_exhausted", budget_error)
        output = final_output(manifest, state)
        self.runs.update_run(
            run.run_id, status="completed", stop_reason="completed",
            state=state, output=output,
        )
        self.runs.append_event(
            run_id=run.run_id,
            name="flow.run.completed",
            payload={"flowId": manifest.id, "output": output},
        )
        metrics = state.get("metrics", {})
        emit_event(
            "flow.run.completed",
            tenant_id=run.tenant_id,
            partition_key=run.run_id,
            data={
                "status": "completed",
                "costUsd": float(metrics.get("cost_usd", 0.0)),
                "tokens": int(metrics.get("tokens", 0.0)),
            },
            subject={"runId": run.run_id},
        )
        result = self.runs.get_run(run.run_id)
        if result is None:  # pragma: no cover - the run was just persisted
            raise FlowRunError(f"run {run.run_id!r} vanished after completion")
        return result

    def _fail_run(
        self,
        run_id: str,
        state: dict[str, Any],
        reason: str,
        detail: str,
    ) -> FlowRunRecord:
        """Mark a run failed (fail closed) and emit ``flow.run.failed``.

        Args:
            run_id: Id of the run to fail.
            state: Final state to persist.
            reason: Machine-readable stop reason.
            detail: Human-readable failure detail.

        Returns:
            The terminal run record.
        """
        self.runs.update_run(run_id, status="failed", stop_reason=reason, state=state)
        self.runs.append_event(
            run_id=run_id,
            name="flow.run.failed",
            payload={"reason": reason, "detail": detail},
        )
        record = self.runs.get_run(run_id)
        if record is None:  # pragma: no cover - the run was just persisted
            raise FlowRunError(f"run {run_id!r} vanished while failing")
        emit_event(
            "flow.run.failed",
            tenant_id=record.tenant_id,
            partition_key=run_id,
            data={"error": detail, "failedStep": str(state.get("cursor") or "")},
            subject={"runId": run_id},
        )
        return record


__all__ = ["FlowEngine", "FlowReplayReport", "FlowRunError"]
