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

def _string(value: Any) -> str:
    """Coerce a manifest scalar to a string, returning ``""`` for non-strings."""
    return value if isinstance(value, str) else ""


def _parse_ref(value: Any, node_id: str, errors: list[str]) -> FlowNodeRef | None:
    """Parse a node ``ref`` of the form ``namespace/name[@range]``.

    Args:
        value: Raw ``ref`` value from the manifest.
        node_id: Id of the node the ref belongs to, for error messages.
        errors: Accumulator for validation errors.

    Returns:
        The parsed reference, or ``None`` when invalid or absent.
    """
    text = _string(value)
    if not text:
        errors.append(f"nodes.{node_id}.ref is required for this node type")
        return None
    ref_id, _, version_range = text.partition("@")
    version_range = version_range.strip() or "*"
    if not FLOW_ID_RE.match(ref_id):
        errors.append(f"nodes.{node_id}.ref must use namespace/name kebab-case format")
        return None
    if not _is_supported_range(version_range):
        errors.append(f"nodes.{node_id}.ref has an invalid version range {version_range!r}")
        return None
    return FlowNodeRef(id=ref_id, version_range=version_range)


def _parse_retries(
    value: Any, context: str, errors: list[str]
) -> FlowRetryPolicy | None:
    """Parse a ``retries`` block.

    Args:
        value: Raw ``retries`` mapping.
        context: Dotted location for error messages.
        errors: Accumulator for validation errors.

    Returns:
        The parsed policy, or ``None`` when absent/invalid.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append(f"{context} must be an object")
        return None
    max_attempts = value.get("maxAttempts", DEFAULT_FLOW_RETRIES.max_attempts)
    backoff = value.get("backoff", DEFAULT_FLOW_RETRIES.backoff)
    initial_delay = value.get("initialDelaySec", DEFAULT_FLOW_RETRIES.initial_delay_sec)
    if not isinstance(max_attempts, int) or max_attempts < 1:
        errors.append(f"{context}.maxAttempts must be an integer >= 1")
        return None
    if backoff not in BACKOFF_MODES:
        errors.append(f"{context}.backoff must be one of {sorted(BACKOFF_MODES)}")
        return None
    if not isinstance(initial_delay, (int, float)) or initial_delay < 0:
        errors.append(f"{context}.initialDelaySec must be a non-negative number")
        return None
    return FlowRetryPolicy(
        max_attempts=max_attempts,
        backoff=str(backoff),
        initial_delay_sec=float(initial_delay),
    )


def _parse_timeout(value: Any, context: str, errors: list[str]) -> int | None:
    """Parse a ``timeoutSec`` value.

    Args:
        value: Raw timeout value.
        context: Dotted location for error messages.
        errors: Accumulator for validation errors.

    Returns:
        The timeout in seconds, or ``None`` when absent/invalid.
    """
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        errors.append(f"{context} must be an integer >= 1")
        return None
    return value


def _parse_io(value: Any, key: str, errors: list[str]) -> FlowIO | None:
    """Parse the flow ``input``/``output`` schema block.

    Args:
        value: Raw schema block.
        key: ``"input"`` or ``"output"``, for error messages.
        errors: Accumulator for validation errors.

    Returns:
        The parsed schema, or ``None`` when absent/invalid.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append(f"{key} must be a JSON Schema object")
        return None
    schema = {k: v for k, v in value.items() if k != "schemaVersion"}
    return FlowIO(
        schema_version=_string(value.get("schemaVersion")) or "1",
        schema=schema,
    )


def _normalize_on_key(item: dict[Any, Any]) -> dict[str, Any]:
    """Map a YAML 1.1 boolean-parsed ``on:`` key back to the string ``"on"``.

    PyYAML implements YAML 1.1, where a bare ``on`` scalar — including when
    used as a mapping key — parses as boolean ``True``. Manifests naturally
    write ``on: flow.run.requested`` and ``on: timeout``, so tolerate both
    spellings.

    Args:
        item: Raw mapping possibly containing a ``True`` key.

    Returns:
        The mapping with the ``True`` key renamed to ``"on"`` when needed.
    """
    if True in item and "on" not in item:
        normalized = {k: v for k, v in item.items() if k is not True}
        normalized["on"] = item[True]
        return normalized
    return {str(k): v for k, v in item.items()}


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
    "version_in_range",
]
