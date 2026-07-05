"""``flow.yaml`` parsing and validation for the v2 Orchestration Engine.

A flow manifest declares a versioned graph of nodes (agent, skill, tool,
conditional, human, subflow, map) connected by optionally guarded edges. The
typed model lives in :mod:`backend.flows.model`; structural graph validation
lives in :mod:`backend.flows.graph`. This module turns a raw ``flow.yaml``
document into a validated :class:`FlowManifest`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.flows.fields import (
    _normalize_on_key,
    _parse_io,
    _parse_ref,
    _parse_retries,
    _parse_timeout,
    _string,
)
from backend.flows.graph import validate_graph
from backend.flows.model import (
    BACKOFF_MODES,
    DEFAULT_FLOW_BUDGETS,
    DEFAULT_FLOW_RETRIES,
    FLOW_ID_RE,
    FLOW_NODE_TYPES,
    FLOW_SCHEMA_VERSION,
    NODE_ID_RE,
    REDUCE_MODES,
    REF_NODE_TYPES,
    TRIGGER_TYPES,
    FlowBudgets,
    FlowDefaults,
    FlowEdge,
    FlowIO,
    FlowManifest,
    FlowManifestValidationResult,
    FlowNode,
    FlowNodeRef,
    FlowRetryPolicy,
    FlowTrigger,
    _is_semver,
    _is_supported_range,
    version_in_range,
)

def _parse_triggers(value: Any, errors: list[str]) -> list[FlowTrigger]:
    """Parse the ``triggers`` list.

    Args:
        value: Raw triggers value.
        errors: Accumulator for validation errors.

    Returns:
        The parsed triggers; empty on absence or error.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append("triggers must be a list")
        return []
    triggers: list[FlowTrigger] = []
    for index, item in enumerate(value):
        prefix = f"triggers[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        item = _normalize_on_key(item)
        trigger_type = _string(item.get("type"))
        if trigger_type not in TRIGGER_TYPES:
            errors.append(f"{prefix}.type must be one of {sorted(TRIGGER_TYPES)}")
            continue
        on = _string(item.get("on")) or None
        schedule = _string(item.get("schedule")) or None
        if trigger_type == "event" and not on:
            errors.append(f"{prefix}.on is required for event triggers")
            continue
        if trigger_type == "cron" and not schedule:
            errors.append(f"{prefix}.schedule is required for cron triggers")
            continue
        metadata = {
            k: v for k, v in item.items() if k not in {"type", "on", "schedule"}
        }
        triggers.append(
            FlowTrigger(type=trigger_type, on=on, schedule=schedule, metadata=metadata)
        )
    return triggers


def _parse_budgets(value: Any, errors: list[str]) -> FlowBudgets:
    """Parse the ``budgets`` block, falling back to safe defaults.

    Args:
        value: Raw budgets mapping.
        errors: Accumulator for validation errors.

    Returns:
        The parsed budgets; defaults on absence.
    """
    if value is None:
        return DEFAULT_FLOW_BUDGETS
    if not isinstance(value, dict):
        errors.append("budgets must be an object")
        return DEFAULT_FLOW_BUDGETS
    cost = value.get("maxCostUsd", DEFAULT_FLOW_BUDGETS.max_cost_usd)
    wall = value.get("maxWallClockSec", DEFAULT_FLOW_BUDGETS.max_wall_clock_sec)
    tokens = value.get("maxTokens", DEFAULT_FLOW_BUDGETS.max_tokens)
    if not isinstance(cost, (int, float)) or cost <= 0:
        errors.append("budgets.maxCostUsd must be a positive number")
        return DEFAULT_FLOW_BUDGETS
    if not isinstance(wall, int) or wall < 1:
        errors.append("budgets.maxWallClockSec must be an integer >= 1")
        return DEFAULT_FLOW_BUDGETS
    if not isinstance(tokens, int) or tokens < 1:
        errors.append("budgets.maxTokens must be an integer >= 1")
        return DEFAULT_FLOW_BUDGETS
    return FlowBudgets(
        max_cost_usd=float(cost), max_wall_clock_sec=wall, max_tokens=tokens
    )


def _parse_node(item: Any, index: int, errors: list[str]) -> FlowNode | None:
    """Parse one entry of the ``nodes`` list.

    Args:
        item: Raw node mapping.
        index: Position in the list, for error messages.
        errors: Accumulator for validation errors.

    Returns:
        The parsed node, or ``None`` when invalid.
    """
    if not isinstance(item, dict):
        errors.append(f"nodes[{index}] must be an object")
        return None
    node_id = _string(item.get("id"))
    node_type = _string(item.get("type"))
    if not node_id or not NODE_ID_RE.match(node_id):
        errors.append(f"nodes[{index}].id must be a kebab-case identifier")
        return None
    if node_type not in FLOW_NODE_TYPES:
        errors.append(
            f"nodes.{node_id}.type must be one of {sorted(FLOW_NODE_TYPES)}"
        )
        return None

    ref: FlowNodeRef | None = None
    if node_type in REF_NODE_TYPES:
        ref = _parse_ref(item.get("ref"), node_id, errors)
    elif item.get("ref") is not None:
        errors.append(f"nodes.{node_id}.ref is not allowed on {node_type} nodes")

    input_bindings = item.get("input", {})
    if not isinstance(input_bindings, dict):
        errors.append(f"nodes.{node_id}.input must be an object")
        input_bindings = {}

    prompt = _string(item.get("prompt")) or None
    form = item.get("form")
    if form is not None and not isinstance(form, dict):
        errors.append(f"nodes.{node_id}.form must be a JSON Schema object")
        form = None
    if node_type == "human" and not prompt:
        errors.append(f"nodes.{node_id}.prompt is required for human nodes")

    over = _string(item.get("over")) or None
    if node_type == "map" and not over:
        errors.append(f"nodes.{node_id}.over is required for map nodes")
    if node_type != "map" and over:
        errors.append(f"nodes.{node_id}.over is only allowed on map nodes")

    reduce_mode = _string(item.get("reduce")) or "collect"
    if reduce_mode not in REDUCE_MODES:
        errors.append(f"nodes.{node_id}.reduce must be one of {sorted(REDUCE_MODES)}")
        reduce_mode = "collect"

    max_parallel = item.get("maxParallel")
    if max_parallel is not None and (
        not isinstance(max_parallel, int) or max_parallel < 1
    ):
        errors.append(f"nodes.{node_id}.maxParallel must be an integer >= 1")
        max_parallel = None

    return FlowNode(
        id=node_id,
        type=node_type,
        ref=ref,
        input_bindings=dict(input_bindings),
        prompt=prompt,
        form=dict(form) if isinstance(form, dict) else None,
        timeout_sec=_parse_timeout(
            item.get("timeoutSec"), f"nodes.{node_id}.timeoutSec", errors
        ),
        on_timeout=_string(item.get("onTimeout")) or None,
        retries=_parse_retries(
            item.get("retries"), f"nodes.{node_id}.retries", errors
        ),
        over=over,
        reduce=reduce_mode,
        max_parallel=max_parallel,
        raw=dict(item),
    )


def _parse_edges(value: Any, errors: list[str]) -> list[FlowEdge]:
    """Parse the ``edges`` list.

    Args:
        value: Raw edges value.
        errors: Accumulator for validation errors.

    Returns:
        The parsed edges; empty on absence or error.
    """
    if not isinstance(value, list):
        errors.append("edges must be a list")
        return []
    edges: list[FlowEdge] = []
    for index, item in enumerate(value):
        prefix = f"edges[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        item = _normalize_on_key(item)
        source = _string(item.get("from"))
        target = _string(item.get("to"))
        if not source or not target:
            errors.append(f"{prefix} must declare both 'from' and 'to'")
            continue
        when = _string(item.get("when")) or None
        on = _string(item.get("on")) or None
        if when is not None and on is not None:
            errors.append(f"{prefix} cannot declare both 'when' and 'on'")
            continue
        edges.append(FlowEdge(source=source, target=target, when=when, on=on))
    return edges


def validate_flow_manifest(raw: dict[str, Any]) -> FlowManifestValidationResult:
    """Validate a raw flow manifest and parse it into a :class:`FlowManifest`.

    Performs field-level validation, then structural graph validation
    (via :func:`backend.flows.graph.validate_graph`): duplicate ids, unknown
    edge endpoints, entry/terminal shape, unconditional cycles, guard
    consistency, and template-binding references.

    Args:
        raw: Parsed ``flow.yaml`` document, keyed by camelCase field names.

    Returns:
        A result carrying the parsed manifest when valid, or the list of
        validation error messages when not.
    """
    errors: list[str] = []
    for key in ("schemaVersion", "id", "version", "hostApi", "nodes", "edges"):
        if key not in raw:
            errors.append(f"{key} is required")

    schema_version = _string(raw.get("schemaVersion"))
    flow_id = _string(raw.get("id"))
    version = _string(raw.get("version"))
    host_api = _string(raw.get("hostApi"))

    if schema_version and schema_version != FLOW_SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {FLOW_SCHEMA_VERSION!r}")
    if flow_id and not FLOW_ID_RE.match(flow_id):
        errors.append("id must use namespace/name kebab-case format")
    if version and not _is_semver(version):
        errors.append("version must be SemVer MAJOR.MINOR.PATCH")
    if host_api and not _is_supported_range(host_api):
        errors.append("hostApi must be a supported range expression")

    triggers = _parse_triggers(raw.get("triggers"), errors)
    flow_input = _parse_io(raw.get("input"), "input", errors)
    flow_output = _parse_io(raw.get("output"), "output", errors)
    budgets = _parse_budgets(raw.get("budgets"), errors)

    defaults_raw = raw.get("defaults")
    defaults = FlowDefaults()
    if defaults_raw is not None:
        if not isinstance(defaults_raw, dict):
            errors.append("defaults must be an object")
        else:
            retries = _parse_retries(
                defaults_raw.get("retries"), "defaults.retries", errors
            )
            timeout = _parse_timeout(
                defaults_raw.get("timeoutSec"), "defaults.timeoutSec", errors
            )
            defaults = FlowDefaults(
                retries=retries or DEFAULT_FLOW_RETRIES, timeout_sec=timeout
            )

    nodes: list[FlowNode] = []
    raw_nodes = raw.get("nodes")
    if raw_nodes is not None and not isinstance(raw_nodes, list):
        errors.append("nodes must be a list")
    elif isinstance(raw_nodes, list):
        for index, item in enumerate(raw_nodes):
            node = _parse_node(item, index, errors)
            if node is not None:
                nodes.append(node)

    edges = _parse_edges(raw.get("edges", []), errors) if "edges" in raw else []

    if not errors:
        errors.extend(
            validate_graph(
                nodes=nodes,
                edges=edges,
                input_schema=flow_input.schema if flow_input else None,
            )
        )

    if errors:
        return FlowManifestValidationResult(False, errors)

    return FlowManifestValidationResult(
        True,
        [],
        FlowManifest(
            schema_version=schema_version,
            id=flow_id,
            version=version,
            host_api=host_api,
            name=_string(raw.get("name")) or None,
            description=_string(raw.get("description")) or None,
            triggers=tuple(triggers),
            input=flow_input,
            output=flow_output,
            defaults=defaults,
            nodes=tuple(nodes),
            edges=tuple(edges),
            budgets=budgets,
            raw=dict(raw),
        ),
    )


def load_flow_manifest(path: Path | str) -> FlowManifest:
    """Load and validate a ``flow.yaml`` manifest from disk.

    Args:
        path: Path to the ``flow.yaml`` file.

    Returns:
        The parsed and validated :class:`FlowManifest`.

    Raises:
        ValueError: If the document is not a mapping or fails validation.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("flow.yaml must contain a mapping at the document root")
    result = validate_flow_manifest(raw)
    if not result.valid or result.manifest is None:
        raise ValueError("; ".join(result.errors))
    return result.manifest


def validate_run_input(
    manifest: FlowManifest, run_input: dict[str, Any]
) -> list[str]:
    """Validate a run input payload against the flow's declared input schema.

    Enforces the schema's ``required`` list and rejects non-declared
    properties when the schema declares ``properties`` and sets
    ``additionalProperties: false``.

    Args:
        manifest: The flow definition.
        run_input: The run input payload.

    Returns:
        Validation error messages; empty when the input is valid.
    """
    if manifest.input is None:
        return []
    errors: list[str] = []
    schema = manifest.input.schema
    required = schema.get("required")
    if isinstance(required, list):
        missing = [key for key in required if key not in run_input]
        if missing:
            errors.append(f"missing required input fields: {missing}")
    properties = schema.get("properties")
    if isinstance(properties, dict) and schema.get("additionalProperties") is False:
        unknown = [key for key in run_input if key not in properties]
        if unknown:
            errors.append(f"unknown input fields: {unknown}")
    return errors


__all__ = [
    "BACKOFF_MODES",
    "DEFAULT_FLOW_BUDGETS",
    "DEFAULT_FLOW_RETRIES",
    "FLOW_NODE_TYPES",
    "FLOW_SCHEMA_VERSION",
    "FlowBudgets",
    "FlowDefaults",
    "FlowEdge",
    "FlowIO",
    "FlowManifest",
    "FlowManifestValidationResult",
    "FlowNode",
    "FlowNodeRef",
    "FlowRetryPolicy",
    "FlowTrigger",
    "REF_NODE_TYPES",
    "TRIGGER_TYPES",
    "load_flow_manifest",
    "validate_flow_manifest",
    "validate_run_input",
    "version_in_range",
]
