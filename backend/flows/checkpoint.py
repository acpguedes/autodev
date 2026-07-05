"""Checkpointing, retry backoff, and deterministic-replay helpers (E3-S3).

The engine's per-step persistence of the cursor, node outputs, and metrics
into ``flow_runs.state_json`` **is** the checkpoint mechanism; this module
formalizes what is derived from those checkpoints. The determinism boundary
(ADR-005) splits a run into *recorded effects* (node outputs — LLM/tool/agent
results — which replay never re-executes) and *pure derivation* (input-binding
rendering, predicate evaluation, and edge selection, which must be functions
of persisted state alone). :func:`replay_decision_path` re-runs only the pure
side and compares it with the recorded trace.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from backend.flows.expressions import (
    ExpressionError,
    evaluate_expression,
    render_template,
)
from backend.flows.handlers import FlowNodeError
from backend.flows.model import FlowManifest, FlowNode, FlowRetryPolicy
from backend.flows.records import FlowRunRecord, FlowStepRecord

MAX_BACKOFF_DELAY_SEC = 3600.0
"""Ceiling for engine-derived exponential backoff delays (one hour).

Exponential growth is derived by the engine, not declared verbatim in the
manifest, so capping the derived value keeps absurd ``maxAttempts`` values
from overflowing ``float`` or sleeping for centuries. Fixed delays are used
exactly as declared.
"""


@dataclass(frozen=True)
class FlowReplayReport:
    """Outcome of replaying a terminal run against its persisted trace.

    Attributes:
        run_id: Id of the replayed run.
        flow_id: Fully qualified id of the flow that was executed.
        deterministic: Whether the replayed decision path matches the
            recorded one exactly (sequence, bindings, and final cursor).
        recorded_sequence: Node ids of the run's completed steps, in
            activation order, as persisted by the original execution.
        replayed_sequence: Node ids derived by re-evaluating every routing
            decision against the rebuilt state.
        divergences: Human-readable descriptions of every detected
            divergence; empty when ``deterministic`` is ``True``.
    """

    run_id: str
    flow_id: str
    deterministic: bool
    recorded_sequence: tuple[str, ...]
    replayed_sequence: tuple[str, ...]
    divergences: tuple[str, ...] = ()

    def to_document(self) -> dict[str, Any]:
        """Render the report as a JSON-serializable document.

        Returns:
            A dict suitable for event payloads and API responses.
        """
        return {
            "schemaVersion": "1",
            "runId": self.run_id,
            "flowId": self.flow_id,
            "deterministic": self.deterministic,
            "recordedSequence": list(self.recorded_sequence),
            "replayedSequence": list(self.replayed_sequence),
            "divergences": list(self.divergences),
        }


def backoff_delay(policy: FlowRetryPolicy, failed_attempt: int) -> float:
    """Compute the delay to sleep after a failed attempt.

    Args:
        policy: The effective retry policy of the node.
        failed_attempt: 1-based number of the attempt that just failed.

    Returns:
        ``initial_delay_sec`` for ``fixed`` backoff, or
        ``initial_delay_sec * 2 ** (failed_attempt - 1)`` for
        ``exponential`` backoff, capped at
        :data:`MAX_BACKOFF_DELAY_SEC`, in seconds.
    """
    if policy.backoff == "exponential":
        exponent = min(max(failed_attempt - 1, 0), 63)
        return min(
            policy.initial_delay_sec * float(2**exponent), MAX_BACKOFF_DELAY_SEC
        )
    return policy.initial_delay_sec


def canonical_output(output: dict[str, Any]) -> dict[str, Any]:
    """Round-trip a node output through JSON (determinism boundary, ADR-005).

    Live routing must observe exactly what resume and replay will later read
    back from the store, so every node output is canonicalized to its JSON
    form before it is recorded or folded into run state. Outputs that cannot
    survive the round trip fail closed instead of routing on values that a
    replay could never rebuild.

    Args:
        output: The node output document.

    Returns:
        The JSON-canonical equivalent of ``output``.

    Raises:
        FlowNodeError: If the output is not JSON-serializable.
    """
    try:
        canonical: dict[str, Any] = json.loads(json.dumps(output))
    except (TypeError, ValueError) as exc:
        raise FlowNodeError(
            f"node output is not JSON-serializable: {exc}"
        ) from exc
    return canonical


def build_eval_state(
    run_input: dict[str, Any], nodes: dict[str, Any]
) -> dict[str, Any]:
    """Build the document flow expressions are evaluated against.

    Both live execution and replay must derive bindings and predicates from
    this exact shape, so it is defined once here (ADR-005).

    Args:
        run_input: The run's input payload.
        nodes: The ``state.nodes`` document mapping node ids to their
            recorded outputs.

    Returns:
        A dict exposing ``flow.input`` and ``nodes.<id>.output``.
    """
    return {"flow": {"input": run_input}, "nodes": nodes}


def select_next_node(
    manifest: FlowManifest,
    node: FlowNode,
    eval_state: dict[str, Any],
) -> str | None:
    """Pick the next node from the current node's outgoing edges.

    ``when``-guarded edges are evaluated in declaration order and the first
    match wins; otherwise the single unguarded edge is taken. ``on``-signal
    edges are never taken by normal completion. When edges exist but none
    match, routing fails closed. This is a pure function of the manifest and
    the evaluation state — the same routine drives live execution and replay
    (ADR-005).

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


def final_output(manifest: FlowManifest, state: dict[str, Any]) -> dict[str, Any]:
    """Compute a run's consolidated output from its checkpointed state.

    The output of the last completed node wins; flows that need a richer
    consolidation should end in a dedicated aggregation node.

    Args:
        manifest: The flow definition.
        state: The run's final checkpointed state.

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


def replay_decision_path(
    manifest: FlowManifest,
    run: FlowRunRecord,
    steps: list[FlowStepRecord],
) -> FlowReplayReport:
    """Re-derive a run's decision path purely from persisted state.

    Recorded node outputs are treated as effects and folded into the rebuilt
    state in activation order; input-binding rendering and edge selection are
    re-executed as pure functions of that state. The derived node sequence is
    compared position-by-position with the recorded sequence of completed
    steps, and the final derived cursor with the run's persisted final
    cursor. A run that failed at a routing decision (``predicate_error`` /
    ``no_route``) is deterministic when replay reproduces that same failure
    at the same node. Replay never raises for trace problems: every anomaly
    is reported as a divergence (fail closed on determinism, not on the
    caller).

    Args:
        manifest: The flow definition the run executed.
        run: The terminal run record.
        steps: The run's persisted steps, in activation order.

    Returns:
        A :class:`FlowReplayReport` describing the comparison.
    """
    recorded = [step for step in steps if step.status == "completed"]
    recorded_sequence = tuple(step.node_id for step in recorded)
    replayed: list[str] = []
    divergences: list[str] = []
    nodes_state: dict[str, Any] = {}
    try:
        cursor: str | None = manifest.entry_node().id
    except ValueError as exc:
        return FlowReplayReport(
            run_id=run.run_id,
            flow_id=run.flow_id,
            deterministic=False,
            recorded_sequence=recorded_sequence,
            replayed_sequence=(),
            divergences=(f"flow has no derivable entry node: {exc}",),
        )

    for index, step in enumerate(recorded):
        if cursor is None:
            divergences.append(
                f"position {index}: replay reached a terminal cursor but the "
                f"trace records node {step.node_id!r}"
            )
            break
        replayed.append(cursor)
        if cursor != step.node_id:
            divergences.append(
                f"position {index}: replay derived node {cursor!r} but the "
                f"trace records node {step.node_id!r}"
            )
            break
        node = manifest.node(step.node_id)
        eval_doc = build_eval_state(run.input, nodes_state)
        try:
            rendered = render_template(dict(node.input_bindings), eval_doc)
        except ExpressionError as exc:
            divergences.append(
                f"position {index}: bindings of node {node.id!r} failed to "
                f"render on replay: {exc}"
            )
            break
        rendered_input = (
            rendered if isinstance(rendered, dict) else {"value": rendered}
        )
        if rendered_input != step.input:
            divergences.append(
                f"position {index}: replayed input of node {node.id!r} "
                "differs from the recorded step input"
            )
        nodes_state[step.node_id] = {
            "output": step.output if isinstance(step.output, dict) else {}
        }
        try:
            cursor = select_next_node(
                manifest, node, build_eval_state(run.input, nodes_state)
            )
        except Exception as exc:  # noqa: BLE001 - replay reports, never raises
            if (
                index == len(recorded) - 1
                and run.stop_reason in ("predicate_error", "no_route")
                and step.node_id == run.state.get("cursor")
            ):
                # The recorded run failed at this exact routing decision;
                # reproducing that failure IS the deterministic outcome.
                return FlowReplayReport(
                    run_id=run.run_id,
                    flow_id=run.flow_id,
                    deterministic=not divergences,
                    recorded_sequence=recorded_sequence,
                    replayed_sequence=tuple(replayed),
                    divergences=tuple(divergences),
                )
            divergences.append(
                f"position {index}: routing after node {node.id!r} failed on "
                f"replay: {exc}"
            )
            cursor = None
            break

    if not divergences and len(replayed) == len(recorded_sequence):
        recorded_final = run.state.get("cursor")
        if cursor != recorded_final:
            divergences.append(
                f"final cursor: replay derived {cursor!r} but the trace "
                f"records {recorded_final!r}"
            )

    return FlowReplayReport(
        run_id=run.run_id,
        flow_id=run.flow_id,
        deterministic=not divergences,
        recorded_sequence=recorded_sequence,
        replayed_sequence=tuple(replayed),
        divergences=tuple(divergences),
    )


__all__ = [
    "FlowReplayReport",
    "backoff_delay",
    "build_eval_state",
    "canonical_output",
    "final_output",
    "replay_decision_path",
    "select_next_node",
]
