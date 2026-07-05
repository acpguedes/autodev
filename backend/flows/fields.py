"""Field-level parsers shared by the ``flow.yaml`` document parser."""

from __future__ import annotations

from typing import Any

from backend.flows.model import (
    BACKOFF_MODES,
    DEFAULT_FLOW_RETRIES,
    FLOW_ID_RE,
    FlowIO,
    FlowNodeRef,
    FlowRetryPolicy,
    _is_supported_range,
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



__all__ = [
    "_normalize_on_key",
    "_parse_io",
    "_parse_ref",
    "_parse_retries",
    "_parse_timeout",
    "_string",
]
