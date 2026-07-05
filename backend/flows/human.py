"""Human-in-the-loop decision service for the Flow Engine (E3-S4).

A ``human`` node pauses its run: the engine persists the step as
``waiting_human``, keeps the cursor on the node, stores pause metadata in the
run state, and emits ``flow.run.paused`` (see :mod:`backend.flows.pause`).
:class:`FlowHumanService` owns the rest of the lifecycle: exposing the pending
request, recording a decision (with optional edits to prior node outputs), and
expiring overdue waits through the node's ``on: timeout`` edge. Decisions on
expired waits fail closed on the SLA: the timeout route is taken instead of
the decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from backend.flows.checkpoint import build_eval_state, select_next_node
from backend.flows.expressions import ExpressionError
from backend.flows.handlers import FlowNodeError
from backend.flows.model import FlowManifest, FlowNode
from backend.flows.pause import (
    FlowHumanDecisionError,
    FlowHumanError,
    FlowHumanStateError,
    PendingHumanRequest,
    pause_run,
)
from backend.flows.records import FlowRunRecord, FlowStepRecord

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from backend.flows.engine import FlowEngine


class FlowHumanService:
    """Pending-request lookup, decisions, and timeout expiry for human waits.

    The service is a thin orchestrator over the engine: it validates and
    records the decision as the human node's output, applies operator edits to
    prior node outputs, routes through the node's outgoing edges, and resumes
    execution with :meth:`FlowEngine.execute_run`.
    """

    def __init__(
        self,
        *,
        engine: FlowEngine | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            engine: Flow engine sharing the durable store; a default engine on
                the process-wide store is built when omitted.
            now: Wall-clock source used for expiry checks; defaults to the
                engine's injectable ``now`` clock.
        """
        if engine is None:
            from backend.flows.engine import FlowEngine as _FlowEngine

            engine = _FlowEngine()
        self._engine = engine
        self._now = now or engine.now

    # ------------------------------------------------------------------ API

    def pending(self, run_id: str) -> PendingHumanRequest | None:
        """Return the run's pending human request, if it is waiting for one.

        Args:
            run_id: Id of the run.

        Returns:
            The pending request, or ``None`` when the run is not waiting.

        Raises:
            FlowHumanError: If the run is unknown.
        """
        run = self._engine.runs.get_run(run_id)
        if run is None:
            raise FlowHumanError(f"unknown run {run_id!r}")
        if run.status != "waiting_human":
            return None
        manifest = self._engine.registry.resolve(run.flow_id, run.flow_version)
        pause = run.state.get("pause") or {}
        node = manifest.node(str(pause.get("nodeId") or run.state.get("cursor")))
        return PendingHumanRequest(
            run_id=run.run_id,
            node_id=node.id,
            prompt=node.prompt or "",
            form=node.form,
            expires_at=pause.get("expiresAt"),
        )

    def decide(
        self, run_id: str, decision: dict[str, Any], *, actor: str = "anonymous"
    ) -> FlowRunRecord:
        """Record a human decision and resume the paused run.

        The decision payload becomes the human node's output (so ``when``
        edges can route on e.g. ``nodes.<id>.output.decision``). When the
        payload carries ``edits: {<nodeId>: {...}}``, each patch is merged
        into that node's recorded output before routing, letting the human
        alter state seen by downstream bindings and predicates. Expired waits
        fail closed: the timeout route is taken and the decision is rejected.

        Args:
            run_id: Id of the paused run.
            decision: Decision payload, validated against the node's ``form``
                schema (``required`` list; unknown keys are rejected when the
                schema declares ``properties`` and
                ``additionalProperties: false``).
            actor: Identity recorded on the decision event.

        Returns:
            The run record after execution resumed (usually terminal).

        Raises:
            FlowHumanError: If the run is unknown.
            FlowHumanStateError: If the run is not waiting for a decision.
            FlowHumanDecisionError: If the decision is invalid or the wait
                expired (the timeout route is taken before raising).
        """
        run, manifest, node, step = self._waiting_context(run_id)
        pause = run.state.get("pause") or {}
        expires_at = pause.get("expiresAt")
        if expires_at is not None and self._expired(str(expires_at)):
            self._route_timeout(run, manifest, node, step)
            raise FlowHumanDecisionError(
                f"human wait for run {run_id!r} expired at {expires_at}; "
                "the timeout route was taken instead"
            )
        errors = self._validate_decision(node.form, decision)
        if errors:
            raise FlowHumanDecisionError("; ".join(errors))

        state = dict(run.state)
        nodes_state: dict[str, Any] = state.setdefault("nodes", {})
        self._apply_edits(manifest, node, nodes_state, decision.get("edits"))
        payload = dict(decision)
        self._engine.runs.complete_step(
            step.step_id, status="completed", output=payload
        )
        nodes_state[node.id] = {"output": payload}
        state.pop("pause", None)
        self._engine.runs.append_event(
            run_id=run.run_id,
            name="flow.human.decision.recorded",
            payload={
                "nodeId": node.id,
                "stepId": step.step_id,
                "actor": actor,
                "decision": payload,
            },
        )
        return self._resume(run, manifest, node, step, state)

    def expire_due(self, at: datetime | None = None) -> list[str]:
        """Expire every due human wait, routing each run through its timeout.

        Args:
            at: Moment to evaluate expiry against; defaults to the injected
                wall clock.

        Returns:
            Ids of the runs that were routed to their timeout targets.
        """
        expired: list[str] = []
        for run in self._engine.runs.list_runs(status="waiting_human"):
            pause = run.state.get("pause") or {}
            expires_at = pause.get("expiresAt")
            if expires_at is None or not self._expired(str(expires_at), at):
                continue
            manifest = self._engine.registry.resolve(run.flow_id, run.flow_version)
            node = manifest.node(str(pause.get("nodeId") or run.state.get("cursor")))
            step = self._waiting_step(run.run_id, pause.get("stepId"))
            self._route_timeout(run, manifest, node, step)
            expired.append(run.run_id)
        return expired

    # ------------------------------------------------------------- internals

    def _waiting_context(
        self, run_id: str
    ) -> tuple[FlowRunRecord, FlowManifest, FlowNode, FlowStepRecord]:
        """Load and check the run, manifest, human node, and waiting step.

        Args:
            run_id: Id of the run expected to be waiting on a human node.

        Returns:
            The run record, its manifest, the human node, and the waiting step.

        Raises:
            FlowHumanError: If the run is unknown or has no waiting step.
            FlowHumanStateError: If the run is not in ``waiting_human`` status.
        """
        run = self._engine.runs.get_run(run_id)
        if run is None:
            raise FlowHumanError(f"unknown run {run_id!r}")
        if run.status != "waiting_human":
            raise FlowHumanStateError(
                f"run {run_id!r} is not waiting for a human decision "
                f"(status {run.status!r})"
            )
        manifest = self._engine.registry.resolve(run.flow_id, run.flow_version)
        pause = run.state.get("pause") or {}
        node = manifest.node(str(pause.get("nodeId") or run.state.get("cursor")))
        step = self._waiting_step(run.run_id, pause.get("stepId"))
        return run, manifest, node, step

    def _waiting_step(self, run_id: str, step_id: Any) -> FlowStepRecord:
        """Find the run's waiting human step.

        Args:
            run_id: Id of the run.
            step_id: Step id recorded in the pause metadata, when present.

        Returns:
            The waiting step record.

        Raises:
            FlowHumanError: If no waiting human step exists.
        """
        for step in reversed(self._engine.runs.list_steps(run_id)):
            if step_id is not None and step.step_id == str(step_id):
                return step
            if step_id is None and step.status == "waiting_human":
                return step
        raise FlowHumanError(f"run {run_id!r} has no waiting human step")

    def _expired(self, expires_at: str, at: datetime | None = None) -> bool:
        """Whether the wall clock reached the wait's expiry timestamp.

        Args:
            expires_at: ISO-8601 expiry recorded at pause time.
            at: Moment to compare against; defaults to the injected clock.

        Returns:
            ``True`` when the wait is due. Naive datetimes are read as UTC.
        """
        deadline = datetime.fromisoformat(expires_at)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        moment = at if at is not None else self._now()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment >= deadline

    @staticmethod
    def _validate_decision(
        form: dict[str, Any] | None, decision: dict[str, Any]
    ) -> list[str]:
        """Validate a decision against the node's ``form`` JSON Schema.

        Same light-JSON-Schema approach as ``FlowEngine._validate_input``:
        the ``required`` list is enforced, and unknown keys are rejected when
        the schema declares ``properties`` with ``additionalProperties: false``.

        Args:
            form: The human node's decision schema, when declared.
            decision: The decision payload.

        Returns:
            A list of error messages; empty when the decision is valid.
        """
        errors: list[str] = []
        if form is None:
            return errors
        required = form.get("required")
        if isinstance(required, list):
            missing = [key for key in required if key not in decision]
            if missing:
                errors.append(f"missing required decision fields: {missing}")
        properties = form.get("properties")
        if isinstance(properties, dict) and form.get("additionalProperties") is False:
            unknown = [key for key in decision if key not in properties]
            if unknown:
                errors.append(f"unknown decision fields: {unknown}")
        return errors

    @staticmethod
    def _apply_edits(
        manifest: FlowManifest,
        human_node: FlowNode,
        nodes_state: dict[str, Any],
        edits: Any,
    ) -> None:
        """Merge operator edits into prior node outputs (in memory).

        Args:
            manifest: The flow definition, used to reject unknown targets.
            human_node: The human node being decided (not editable).
            nodes_state: The run state's ``nodes`` document, mutated in place.
            edits: The decision's ``edits`` value: ``{<nodeId>: {patch}}``.

        Raises:
            FlowHumanDecisionError: If ``edits`` is malformed, targets an
                unknown node, or targets the human node itself (fail closed).
        """
        if edits is None:
            return
        if not isinstance(edits, dict):
            raise FlowHumanDecisionError(
                "decision 'edits' must be an object keyed by node id"
            )
        for target_id, patch in edits.items():
            if not isinstance(patch, dict):
                raise FlowHumanDecisionError(
                    f"edit for node {target_id!r} must be an object"
                )
            if str(target_id) == human_node.id:
                raise FlowHumanDecisionError(
                    "edits cannot target the human node itself"
                )
            try:
                manifest.node(str(target_id))
            except KeyError as exc:
                raise FlowHumanDecisionError(
                    f"edits reference unknown node {target_id!r}"
                ) from exc
            entry = nodes_state.setdefault(str(target_id), {})
            output = entry.get("output")
            if not isinstance(output, dict):
                output = {}
            entry["output"] = {**output, **patch}

    def _resume(
        self,
        run: FlowRunRecord,
        manifest: FlowManifest,
        node: FlowNode,
        step: FlowStepRecord,
        state: dict[str, Any],
    ) -> FlowRunRecord:
        """Route past the decided human node and continue execution.

        Args:
            run: The run being resumed.
            manifest: The flow definition.
            node: The human node whose decision was just recorded.
            step: The (now completed) human step.
            state: The run state carrying the decision and any edits.

        Returns:
            The run record after the engine loop stopped again.
        """
        eval_state = build_eval_state(run.input, state.get("nodes", {}))
        try:
            next_node = select_next_node(manifest, node, eval_state)
        except ExpressionError as exc:
            return self._engine._fail_run(
                run.run_id, state, "predicate_error",
                f"routing after node {node.id!r}: {exc}",
            )
        except FlowNodeError as exc:
            return self._engine._fail_run(run.run_id, state, "no_route", str(exc))
        state["cursor"] = next_node
        self._engine.runs.update_run(run.run_id, state=state)
        self._engine.runs.append_event(
            run_id=run.run_id,
            name="run.step.completed",
            payload={
                "nodeId": node.id,
                "stepId": step.step_id,
                "attempt": step.attempt,
                "nextNodeId": next_node,
            },
        )
        return self._engine.execute_run(run.run_id)

    def _route_timeout(
        self,
        run: FlowRunRecord,
        manifest: FlowManifest,
        node: FlowNode,
        step: FlowStepRecord,
    ) -> FlowRunRecord:
        """Complete an expired wait through the node's ``on: timeout`` edge.

        The human step completes with output ``{"timedOut": true}``,
        ``flow.human.timeout.expired`` is emitted, and the cursor moves to the
        timeout target before execution resumes. Runs whose human node has no
        timeout edge fail closed (``no_route``).

        Args:
            run: The expired run.
            manifest: The flow definition.
            node: The human node whose wait expired.
            step: The waiting human step.

        Returns:
            The run record after the timeout route executed.
        """
        pause = dict(run.state.get("pause") or {})
        target = node.on_timeout
        if target is None:
            for edge in manifest.edges_from(node.id):
                if edge.on == "timeout":
                    target = edge.target
                    break
        state = dict(run.state)
        nodes_state: dict[str, Any] = state.setdefault("nodes", {})
        output = {"timedOut": True}
        self._engine.runs.complete_step(
            step.step_id, status="completed", output=output
        )
        nodes_state[node.id] = {"output": output}
        state.pop("pause", None)
        self._engine.runs.append_event(
            run_id=run.run_id,
            name="flow.human.timeout.expired",
            payload={
                "nodeId": node.id,
                "stepId": step.step_id,
                "expiresAt": pause.get("expiresAt"),
            },
        )
        if target is None:
            return self._engine._fail_run(
                run.run_id, state, "no_route",
                f"human node {node.id!r} expired without an 'on: timeout' edge",
            )
        state["cursor"] = target
        self._engine.runs.update_run(run.run_id, state=state)
        self._engine.runs.append_event(
            run_id=run.run_id,
            name="run.step.completed",
            payload={
                "nodeId": node.id,
                "stepId": step.step_id,
                "attempt": step.attempt,
                "nextNodeId": target,
            },
        )
        return self._engine.execute_run(run.run_id)


__all__ = [
    "FlowHumanDecisionError",
    "FlowHumanError",
    "FlowHumanService",
    "FlowHumanStateError",
    "PendingHumanRequest",
    "pause_run",
]
