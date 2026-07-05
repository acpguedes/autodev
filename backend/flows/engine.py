"""The Flow Engine: executes declarative flow graphs with durable state.

E3-S2 scope: walk the graph from the entry node, render each node's input
bindings against run state, execute the node through its registered handler,
persist every Run/Step transition, enforce fail-closed run budgets, and emit
ordered lifecycle events (``flow.run.started``, ``run.step.started``,
``run.step.completed``, ``run.step.failed``, ``flow.run.completed``,
``flow.run.failed``) into the durable event store. E3-S4 adds human-in-the-
loop pauses: a ``human`` node stops the loop as ``waiting_human`` (with
``flow.run.paused``) until :mod:`backend.flows.human` resumes the run.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from backend.flows.expressions import ExpressionError, evaluate_expression, render_template
from backend.flows.handlers import (
    FlowHandlerRegistry,
    FlowNodeError,
    NodeContext,
    UnsupportedNodeError,
    build_default_handlers,
)
from backend.flows.model import FlowManifest, FlowNode
from backend.flows.pause import pause_run
from backend.flows.registry import FlowRegistry
from backend.flows.state import FlowRunRecord, FlowRunStore
from backend.observability.tracing import trace_run_step
from backend.persistence.database import get_store


class FlowRunError(RuntimeError):
    """Raised when a run cannot be started (unknown flow, invalid input)."""


class FlowEngine:
    """Executes registered flows with durable, observable Run/Step state."""

    def __init__(
        self,
        *,
        store: Any | None = None,
        registry: FlowRegistry | None = None,
        run_store: FlowRunStore | None = None,
        handlers: FlowHandlerRegistry | None = None,
        clock: Callable[[], float] | None = None,
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
        self._validate_input(manifest, run_input)

        entry_id = manifest.entry_node().id
        run = self.runs.create_run(
            flow_id=manifest.id,
            flow_version=manifest.version,
            tenant_id=tenant_id,
            trigger=dict(trigger or {"type": "api"}),
            input=run_input,
            state={
                "cursor": entry_id,
                "nodes": {},
                "metrics": {"tokens": 0.0, "cost_usd": 0.0},
            },
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
        if execute:
            return self.execute_run(run.run_id)
        return run

    def execute_run(self, run_id: str) -> FlowRunRecord:
        """Execute a run from its persisted cursor until it stops.

        Args:
            run_id: Id of the run to execute.

        Returns:
            The terminal (or paused) run record.

        Raises:
            FlowRunError: If the run or its flow definition is unknown.
        """
        run = self.runs.get_run(run_id)
        if run is None:
            raise FlowRunError(f"unknown run {run_id!r}")
        manifest = self.registry.resolve(run.flow_id, run.flow_version)
        self.runs.update_run(run.run_id, status="running")

        state = dict(run.state)
        state.setdefault("cursor", manifest.entry_node().id)
        state.setdefault("nodes", {})
        state.setdefault("metrics", {"tokens": 0.0, "cost_usd": 0.0})
        started = self._clock()
        activations = 0

        while state.get("cursor"):
            budget_error = self._budget_violation(manifest, state, started, activations)
            if budget_error is not None:
                return self._fail_run(run.run_id, state, "budget_exhausted", budget_error)

            node = manifest.node(str(state["cursor"]))
            outcome_record = self._activate_node(run, manifest, node, state)
            if outcome_record is not None:
                return outcome_record
            activations += 1

        output = self._final_output(manifest, state)
        self.runs.update_run(
            run.run_id, status="completed", stop_reason="completed",
            state=state, output=output,
        )
        self.runs.append_event(
            run_id=run.run_id,
            name="flow.run.completed",
            payload={"flowId": manifest.id, "output": output},
        )
        result = self.runs.get_run(run.run_id)
        assert result is not None  # noqa: S101 - just persisted above
        return result

    # ------------------------------------------------------------- internals

    def _activate_node(
        self,
        run: FlowRunRecord,
        manifest: FlowManifest,
        node: FlowNode,
        state: dict[str, Any],
    ) -> FlowRunRecord | None:
        """Execute one node activation and advance the cursor.

        Args:
            run: The run being executed.
            manifest: The flow definition.
            node: The node at the cursor.
            state: The mutable run state (updated in place and persisted).

        Returns:
            A run record when the run stopped (failed, or paused at a human
            node); ``None`` to continue the loop.
        """
        eval_state = self._eval_state(run, state)
        try:
            rendered = render_template(dict(node.input_bindings), eval_state)
        except ExpressionError as exc:
            return self._fail_run(
                run.run_id, state, "binding_error",
                f"node {node.id!r}: {exc}",
            )

        step = self.runs.create_step(
            run_id=run.run_id,
            node_id=node.id,
            node_type=node.type,
            attempt=1,
            input=rendered if isinstance(rendered, dict) else {"value": rendered},
        )
        self.runs.append_event(
            run_id=run.run_id,
            name="run.step.started",
            payload={"nodeId": node.id, "stepId": step.step_id, "attempt": step.attempt},
        )

        ctx = NodeContext(
            manifest=manifest,
            node=node,
            run_id=run.run_id,
            tenant_id=run.tenant_id,
            input=rendered if isinstance(rendered, dict) else {"value": rendered},
            state=state,
            services={"engine": self},
        )
        try:
            with trace_run_step(
                run_id=run.run_id,
                step_id=f"{node.id}#{step.attempt}",
                agent=node.ref.id if node.ref else node.type,
                status="running",
            ):
                handler = self.handlers.get(node.type)
                outcome = handler(ctx)
        except Exception as exc:  # noqa: BLE001 - engine isolates node failures
            reason = (
                "unsupported_node"
                if isinstance(exc, UnsupportedNodeError)
                else "node_failed"
            )
            self.runs.complete_step(step.step_id, status="failed", error=str(exc))
            self.runs.append_event(
                run_id=run.run_id,
                name="run.step.failed",
                payload={
                    "nodeId": node.id,
                    "stepId": step.step_id,
                    "attempt": step.attempt,
                    "reason": reason,
                    "error": str(exc),
                },
            )
            return self._fail_run(run.run_id, state, reason, str(exc))

        if outcome.status == "waiting_human":
            return pause_run(self.runs, run, node, step, state, outcome)

        self.runs.complete_step(step.step_id, status="completed", output=outcome.output)
        nodes_state = state["nodes"]
        nodes_state[node.id] = {"output": outcome.output}
        metrics = state["metrics"]
        metrics["tokens"] = float(metrics.get("tokens", 0.0)) + float(
            outcome.metrics.get("tokens", 0.0)
        )
        metrics["cost_usd"] = float(metrics.get("cost_usd", 0.0)) + float(
            outcome.metrics.get("cost_usd", 0.0)
        )

        try:
            next_node = self._select_next(
                manifest, node, self._eval_state(run, state)
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
                "stepId": step.step_id,
                "attempt": step.attempt,
                "nextNodeId": next_node,
            },
        )
        return None

    def _select_next(
        self,
        manifest: FlowManifest,
        node: FlowNode,
        eval_state: dict[str, Any],
    ) -> str | None:
        """Pick the next node from the current node's outgoing edges.

        ``when``-guarded edges are evaluated in declaration order and the
        first match wins; otherwise the single unguarded edge is taken.
        ``on``-signal edges are never taken by normal completion. When edges
        exist but none match, the engine fails closed.

        Args:
            manifest: The flow definition.
            node: The node whose outgoing edges to evaluate.
            eval_state: State document predicates are evaluated against.

        Returns:
            The next node id, or ``None`` when the node is terminal.

        Raises:
            ExpressionError: If a predicate fails to evaluate.
            FlowNodeError: If edges exist but no route matches (fails closed).
        """
        edges = manifest.edges_from(node.id)
        if not edges:
            return None
        for edge in edges:
            if edge.when is None:
                continue
            predicate = edge.when.strip()
            if predicate.startswith("{{") and predicate.endswith("}}"):
                predicate = predicate[2:-2]
            if bool(evaluate_expression(predicate, eval_state)):
                return edge.target
        for edge in edges:
            if not edge.guarded:
                return edge.target
        if all(edge.on is not None for edge in edges):
            return None
        raise FlowNodeError(
            f"no outgoing edge of node {node.id!r} matched the run state"
        )

    def _eval_state(
        self, run: FlowRunRecord, state: dict[str, Any]
    ) -> dict[str, Any]:
        """Build the document expressions are evaluated against.

        Args:
            run: The run being executed.
            state: The run's mutable state.

        Returns:
            A dict exposing ``flow.input`` and ``nodes.<id>.output``.
        """
        return {"flow": {"input": run.input}, "nodes": state.get("nodes", {})}

    def _budget_violation(
        self,
        manifest: FlowManifest,
        state: dict[str, Any],
        started: float,
        activations: int,
    ) -> str | None:
        """Check run budgets, returning a violation description if any.

        Args:
            manifest: The flow definition (source of the budgets).
            state: Run state carrying accumulated metrics.
            started: Monotonic timestamp when this execution session began.
            activations: Node activations performed in this session.

        Returns:
            A human-readable violation, or ``None`` when within budget.
        """
        budgets = manifest.budgets
        elapsed = self._clock() - started
        if elapsed > budgets.max_wall_clock_sec:
            return (
                f"wall clock {elapsed:.1f}s exceeded budget "
                f"{budgets.max_wall_clock_sec}s"
            )
        metrics = state.get("metrics", {})
        if float(metrics.get("tokens", 0.0)) > budgets.max_tokens:
            return f"tokens {metrics.get('tokens')} exceeded budget {budgets.max_tokens}"
        if float(metrics.get("cost_usd", 0.0)) > budgets.max_cost_usd:
            return (
                f"cost {metrics.get('cost_usd')} exceeded budget "
                f"{budgets.max_cost_usd} USD"
            )
        if activations >= self._max_steps:
            return f"engine step cap {self._max_steps} reached"
        return None

    def _final_output(
        self, manifest: FlowManifest, state: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute the consolidated run output.

        The output of the last completed node wins; flows that need a richer
        consolidation should end in a dedicated aggregation node.

        Args:
            manifest: The flow definition.
            state: The run's final state.

        Returns:
            The consolidated output document.
        """
        nodes: dict[str, Any] = state.get("nodes", {})
        last_output: dict[str, Any] = {}
        for node in manifest.nodes:
            entry = nodes.get(node.id)
            if entry is not None and isinstance(entry.get("output"), dict):
                last_output = entry["output"]
        return last_output

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
        assert record is not None  # noqa: S101 - just persisted above
        return record

    @staticmethod
    def _validate_input(manifest: FlowManifest, run_input: dict[str, Any]) -> None:
        """Validate run input against the flow's declared input schema.

        Enforces the schema's ``required`` list and rejects non-declared
        properties when the schema declares ``properties`` and sets
        ``additionalProperties: false``.

        Args:
            manifest: The flow definition.
            run_input: The run input payload.

        Raises:
            FlowRunError: If the input violates the declared schema.
        """
        if manifest.input is None:
            return
        schema = manifest.input.schema
        required = schema.get("required")
        if isinstance(required, list):
            missing = [key for key in required if key not in run_input]
            if missing:
                raise FlowRunError(f"missing required input fields: {missing}")
        properties = schema.get("properties")
        if isinstance(properties, dict) and schema.get("additionalProperties") is False:
            unknown = [key for key in run_input if key not in properties]
            if unknown:
                raise FlowRunError(f"unknown input fields: {unknown}")


__all__ = ["FlowEngine", "FlowRunError"]
