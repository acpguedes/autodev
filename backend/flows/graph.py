"""Structural validation of a flow graph.

Field-level parsing lives in :mod:`backend.flows.manifest`; this module checks
the graph shape: duplicate ids, dangling edges, entry/terminal structure,
reachability, unconditional cycles, guard consistency per node type, and the
state paths referenced by input bindings and edge predicates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.flows.expressions import (
    ExpressionError,
    compile_expression,
    extract_template_paths,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from backend.flows.manifest import FlowEdge, FlowNode

EDGE_SIGNALS = frozenset({"timeout"})


def validate_graph(
    *,
    nodes: list["FlowNode"],
    edges: list["FlowEdge"],
    input_schema: dict[str, Any] | None,
) -> list[str]:
    """Validate the structural rules of a flow graph.

    Args:
        nodes: Parsed flow nodes.
        edges: Parsed flow edges.
        input_schema: The flow's declared input JSON Schema, when present.

    Returns:
        A list of error messages; empty when the graph is valid.
    """
    errors: list[str] = []
    node_ids = [node.id for node in nodes]
    duplicates = {node_id for node_id in node_ids if node_ids.count(node_id) > 1}
    for node_id in sorted(duplicates):
        errors.append(f"duplicate node id {node_id!r}")
    if not nodes:
        errors.append("flow must declare at least one node")
        return errors
    if duplicates:
        return errors

    known = set(node_ids)
    by_id = {node.id: node for node in nodes}
    for edge in edges:
        if edge.source not in known:
            errors.append(f"edge references unknown node {edge.source!r}")
        if edge.target not in known:
            errors.append(f"edge references unknown node {edge.target!r}")
    if errors:
        return errors

    errors.extend(_validate_entry_and_reachability(nodes, edges))
    errors.extend(_validate_guards(by_id, edges))
    errors.extend(_validate_unconditional_cycles(edges))
    errors.extend(_validate_expressions(by_id, edges, input_schema))
    return errors


def _validate_entry_and_reachability(
    nodes: list["FlowNode"], edges: list["FlowEdge"]
) -> list[str]:
    """Require exactly one entry node, one or more terminals, full reachability."""
    errors: list[str] = []
    targets = {edge.target for edge in edges}
    sources = {edge.source for edge in edges}
    entries = [node.id for node in nodes if node.id not in targets]
    if len(entries) != 1:
        errors.append(
            "flow must have exactly one entry node (a node with no incoming edges); "
            f"found {sorted(entries) if entries else 'none'}"
        )
    terminals = [node.id for node in nodes if node.id not in sources]
    if not terminals:
        errors.append("flow must have at least one terminal node (no outgoing edges)")
    if len(entries) == 1:
        reachable: set[str] = set()
        frontier = [entries[0]]
        adjacency: dict[str, list[str]] = {}
        for edge in edges:
            adjacency.setdefault(edge.source, []).append(edge.target)
        while frontier:
            current = frontier.pop()
            if current in reachable:
                continue
            reachable.add(current)
            frontier.extend(adjacency.get(current, []))
        unreachable = sorted({node.id for node in nodes} - reachable)
        if unreachable:
            errors.append(f"unreachable nodes: {unreachable}")
    return errors


def _validate_guards(
    by_id: dict[str, "FlowNode"], edges: list["FlowEdge"]
) -> list[str]:
    """Check guard rules per node type.

    Conditional nodes need at least two guarded out-edges and nothing
    unguarded. Other nodes may have at most one unguarded out-edge. ``on``
    signals are restricted to a known vocabulary, and ``timeout`` edges are
    only valid leaving human nodes with a consistent ``onTimeout``/``timeoutSec``.
    """
    errors: list[str] = []
    outgoing: dict[str, list["FlowEdge"]] = {}
    for edge in edges:
        outgoing.setdefault(edge.source, []).append(edge)

    for edge in edges:
        if edge.on is not None and edge.on not in EDGE_SIGNALS:
            errors.append(
                f"edge {edge.source!r} -> {edge.target!r} has unknown signal "
                f"{edge.on!r}; supported: {sorted(EDGE_SIGNALS)}"
            )
        if edge.on == "timeout" and by_id[edge.source].type != "human":
            errors.append(
                f"edge {edge.source!r} -> {edge.target!r}: 'on: timeout' is only "
                "allowed on edges leaving human nodes"
            )

    for node_id, node in by_id.items():
        node_edges = outgoing.get(node_id, [])
        unguarded = [edge for edge in node_edges if not edge.guarded]
        if node.type == "conditional":
            if len(node_edges) < 2:
                errors.append(
                    f"conditional node {node_id!r} must have at least two outgoing edges"
                )
            if unguarded:
                errors.append(
                    f"conditional node {node_id!r} must guard every outgoing edge "
                    "with 'when' or 'on'"
                )
        elif len(unguarded) > 1:
            errors.append(
                f"node {node_id!r} has {len(unguarded)} unguarded outgoing edges; "
                "at most one is allowed"
            )

        if node.type == "human":
            timeout_edges = [edge for edge in node_edges if edge.on == "timeout"]
            if node.on_timeout is not None:
                if not timeout_edges:
                    errors.append(
                        f"human node {node_id!r} declares onTimeout but has no "
                        "'on: timeout' edge"
                    )
                elif all(edge.target != node.on_timeout for edge in timeout_edges):
                    errors.append(
                        f"human node {node_id!r} onTimeout {node.on_timeout!r} does "
                        "not match any 'on: timeout' edge target"
                    )
            if timeout_edges and node.timeout_sec is None:
                errors.append(
                    f"human node {node_id!r} has an 'on: timeout' edge but no timeoutSec"
                )
        elif node.on_timeout is not None:
            errors.append(f"nodes.{node_id}.onTimeout is only allowed on human nodes")
    return errors


def _validate_unconditional_cycles(edges: list["FlowEdge"]) -> list[str]:
    """Reject cycles made solely of unguarded edges.

    Guarded loops (rework paths) are legal because a predicate can break them;
    a cycle of unconditional edges can never terminate.
    """
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if not edge.guarded:
            adjacency.setdefault(edge.source, []).append(edge.target)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    def visit(node_id: str, stack: list[str]) -> list[str] | None:
        """Depth-first search returning a cycle path when one is found."""
        color[node_id] = GRAY
        stack.append(node_id)
        for neighbor in adjacency.get(node_id, []):
            state = color.get(neighbor, WHITE)
            if state == GRAY:
                return stack[stack.index(neighbor) :] + [neighbor]
            if state == WHITE:
                cycle = visit(neighbor, stack)
                if cycle is not None:
                    return cycle
        stack.pop()
        color[node_id] = BLACK
        return None

    for start in list(adjacency):
        if color.get(start, WHITE) == WHITE:
            cycle = visit(start, [])
            if cycle is not None:
                return [
                    "unconditional cycle detected: "
                    + " -> ".join(cycle)
                    + "; loops must include a 'when' or 'on' guarded edge"
                ]
    return []


def _validate_expressions(
    by_id: dict[str, "FlowNode"],
    edges: list["FlowEdge"],
    input_schema: dict[str, Any] | None,
) -> list[str]:
    """Compile every predicate/binding and check the state paths they reference."""
    errors: list[str] = []
    declared_inputs: set[str] | None = None
    if input_schema is not None and isinstance(input_schema.get("properties"), dict):
        declared_inputs = set(input_schema["properties"])

    for edge in edges:
        if edge.when is None:
            continue
        location = f"edge {edge.source!r} -> {edge.target!r}"
        try:
            paths = compile_expression(_strip_template(edge.when)).paths()
        except ExpressionError as exc:
            errors.append(f"{location}: invalid 'when' expression: {exc}")
            continue
        errors.extend(
            _check_paths(paths, location, by_id, declared_inputs, allow_item=False)
        )

    for node in by_id.values():
        location = f"nodes.{node.id}.input"
        try:
            paths = extract_template_paths(node.input_bindings)
            if node.over is not None:
                paths |= extract_template_paths(node.over)
        except ExpressionError as exc:
            errors.append(f"{location}: invalid template expression: {exc}")
            continue
        errors.extend(
            _check_paths(
                paths,
                location,
                by_id,
                declared_inputs,
                allow_item=node.type == "map",
                self_id=node.id,
            )
        )
    return errors


def _strip_template(value: str) -> str:
    """Strip one layer of ``{{ }}`` braces when present, else return unchanged."""
    text = value.strip()
    if text.startswith("{{") and text.endswith("}}"):
        return text[2:-2]
    return text


def _check_paths(
    paths: set[tuple[str, ...]],
    location: str,
    by_id: dict[str, "FlowNode"],
    declared_inputs: set[str] | None,
    *,
    allow_item: bool,
    self_id: str | None = None,
) -> list[str]:
    """Validate that referenced state paths point at known roots.

    Args:
        paths: Path prefixes referenced by the expression(s).
        location: Dotted location for error messages.
        by_id: Node lookup table.
        declared_inputs: Property names declared by the flow input schema, when
            it declares any.
        allow_item: Whether the ``item`` root is legal (map-node bindings).
        self_id: Id of the node owning the binding, to reject self-references.

    Returns:
        A list of error messages.
    """
    errors: list[str] = []
    for path in sorted(paths):
        root = path[0] if path else ""
        if root == "flow":
            if len(path) >= 2 and path[1] != "input":
                errors.append(f"{location}: unknown flow scope {'.'.join(path[:2])!r}")
            elif (
                declared_inputs is not None
                and len(path) >= 3
                and path[2] not in declared_inputs
            ):
                errors.append(
                    f"{location}: flow.input.{path[2]} is not declared by the input schema"
                )
        elif root == "nodes":
            if len(path) < 2 or path[1] not in by_id:
                referenced = path[1] if len(path) >= 2 else "?"
                errors.append(f"{location}: references unknown node {referenced!r}")
            elif path[1] == self_id:
                errors.append(f"{location}: node cannot reference its own output")
            elif len(path) >= 3 and path[2] != "output":
                errors.append(
                    f"{location}: only node outputs are addressable "
                    f"(nodes.{path[1]}.output...)"
                )
        elif root == "item":
            if not allow_item:
                errors.append(
                    f"{location}: 'item' is only available inside map-node bindings"
                )
        else:
            errors.append(
                f"{location}: unknown state root {root!r}; expected flow, nodes, or item"
            )
    return errors


__all__ = ["EDGE_SIGNALS", "validate_graph"]
