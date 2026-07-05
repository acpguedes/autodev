"""Single-node activation: rendering, retries, backoff, and routing (E3-S3).

Extracted from :mod:`backend.flows.engine` to keep both modules under the
repository's 500-line file cap. :class:`NodeActivationMixin` implements
:meth:`NodeActivationMixin._activate_node`, the routine that drives one node
through its registered handler with the manifest's retry policy, checkpoints
its output, and advances the run cursor; :class:`~backend.flows.engine.FlowEngine`
inherits it and supplies the collaborators (``runs``, ``handlers``, clock,
sleeper) plus ``_fail_run``.
"""

from __future__ import annotations

from typing import Any, Callable

from backend.flows.checkpoint import (
    backoff_delay,
    build_eval_state,
    canonical_output,
    select_next_node,
)
from backend.flows.expressions import ExpressionError, render_template
from backend.flows.handlers import (
    FlowHandlerRegistry,
    FlowNodeError,
    NodeContext,
    NodeOutcome,
    UnsupportedNodeError,
)
from backend.flows.model import FlowManifest, FlowNode
from backend.flows.state import FlowRunRecord, FlowRunStore
from backend.observability.tracing import trace_run_step


class NodeActivationMixin:
    """Mixin implementing single-node activation for :class:`FlowEngine`.

    Declares the collaborators it relies on so mypy can check the method in
    isolation; :class:`~backend.flows.engine.FlowEngine` provides the real
    attributes and overrides :meth:`_fail_run`.
    """

    runs: FlowRunStore
    handlers: FlowHandlerRegistry
    _sleeper: Callable[[float], None]
    _clock: Callable[[], float]

    def _fail_run(
        self,
        run_id: str,
        state: dict[str, Any],
        reason: str,
        detail: str,
    ) -> FlowRunRecord:
        """Mark a run failed (fail closed) and emit ``flow.run.failed``.

        Implemented by the engine.

        Args:
            run_id: Id of the run to fail.
            state: Final state to persist.
            reason: Machine-readable stop reason.
            detail: Human-readable failure detail.

        Returns:
            The terminal run record.
        """
        raise NotImplementedError

    def _activate_node(
        self,
        run: FlowRunRecord,
        manifest: FlowManifest,
        node: FlowNode,
        state: dict[str, Any],
        started: float,
    ) -> FlowRunRecord | None:
        """Execute one node activation, honoring retries, and advance the cursor.

        The rendered input is computed once — bindings are pure functions of
        run state, which does not change between attempts. Each attempt
        persists its own step row (attempt 1, 2, ...) with
        ``run.step.started``/``run.step.failed`` events; the engine sleeps
        the policy's backoff between attempts through the injectable sleeper.
        ``UnsupportedNodeError`` never retries — no later attempt can succeed
        within the same process — and only the final failed attempt fails the
        run.

        Args:
            run: The run being executed.
            manifest: The flow definition.
            node: The node at the cursor.
            state: The mutable run state (updated in place and persisted).
            started: Monotonic-clock instant the run loop started, used to
                enforce the wall-clock budget before backoff sleeps.

        Returns:
            A terminal run record when the run failed; ``None`` to continue.
        """
        eval_state = build_eval_state(run.input, state.get("nodes", {}))
        try:
            rendered = render_template(dict(node.input_bindings), eval_state)
        except ExpressionError as exc:
            return self._fail_run(
                run.run_id, state, "binding_error",
                f"node {node.id!r}: {exc}",
            )
        step_input = rendered if isinstance(rendered, dict) else {"value": rendered}
        policy = node.retries or manifest.defaults.retries

        step = None
        outcome: NodeOutcome | None = None
        for attempt in range(1, max(policy.max_attempts, 1) + 1):
            step = self.runs.create_step(
                run_id=run.run_id,
                node_id=node.id,
                node_type=node.type,
                attempt=attempt,
                input=step_input,
            )
            self.runs.append_event(
                run_id=run.run_id,
                name="run.step.started",
                payload={
                    "nodeId": node.id,
                    "stepId": step.step_id,
                    "attempt": step.attempt,
                },
            )
            ctx = NodeContext(
                manifest=manifest,
                node=node,
                run_id=run.run_id,
                tenant_id=run.tenant_id,
                # Per-attempt copy: a handler mutating its input must not
                # leak the mutation into later attempts' recorded inputs.
                input=dict(step_input),
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
                break
            except Exception as exc:  # noqa: BLE001 - engine isolates node failures
                retryable = not isinstance(exc, UnsupportedNodeError)
                reason = "node_failed" if retryable else "unsupported_node"
                will_retry = retryable and attempt < policy.max_attempts
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
                        "willRetry": will_retry,
                    },
                )
                if not will_retry:
                    return self._fail_run(run.run_id, state, reason, str(exc))
                delay = backoff_delay(policy, attempt)
                budget_error = manifest.budgets.violation(
                    state.get("metrics", {}), self._clock() - started + delay
                )
                if budget_error is not None:
                    return self._fail_run(
                        run.run_id, state, "budget_exhausted",
                        f"retry backoff of node {node.id!r} would breach the "
                        f"run budget: {budget_error}",
                    )
                self._sleeper(delay)
        if step is None or outcome is None:  # pragma: no cover - loop always runs
            from backend.flows.engine import FlowRunError

            raise FlowRunError(f"node {node.id!r} produced no attempt")

        try:
            output = canonical_output(outcome.output)
        except FlowNodeError as exc:
            self.runs.complete_step(step.step_id, status="failed", error=str(exc))
            return self._fail_run(
                run.run_id, state, "node_failed", f"node {node.id!r}: {exc}"
            )
        self.runs.complete_step(step.step_id, status="completed", output=output)
        nodes_state = state["nodes"]
        nodes_state[node.id] = {"output": output}
        metrics = state["metrics"]
        metrics["tokens"] = float(metrics.get("tokens", 0.0)) + float(
            outcome.metrics.get("tokens", 0.0)
        )
        metrics["cost_usd"] = float(metrics.get("cost_usd", 0.0)) + float(
            outcome.metrics.get("cost_usd", 0.0)
        )

        try:
            next_node = select_next_node(
                manifest, node, build_eval_state(run.input, state.get("nodes", {}))
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


__all__ = ["NodeActivationMixin"]
