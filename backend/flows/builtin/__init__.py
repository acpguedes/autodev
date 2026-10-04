"""Built-in flows shipped with AutoDev (E63-S5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.flows.manifest import validate_flow_manifest
from backend.flows.model import FlowManifest

BUILTIN_DIR = Path(__file__).parent


def _fix_on_keys(node: Any) -> Any:
    """Undo YAML 1.1 coercion of the bare ``on:`` key to ``True``."""
    if isinstance(node, dict):
        return {("on" if k is True else k): _fix_on_keys(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_fix_on_keys(v) for v in node]
    return node


def load_builtin_flows() -> list[FlowManifest]:
    """Load and validate every built-in ``*.flow.yaml`` document.

    Returns:
        Validated manifests, ordered by file name.

    Raises:
        ValueError: If a shipped document fails validation (a packaging bug).
    """
    manifests: list[FlowManifest] = []
    for path in sorted(BUILTIN_DIR.glob("*.flow.yaml")):
        raw: dict[str, Any] = _fix_on_keys(yaml.safe_load(path.read_text(encoding="utf-8")))
        result = validate_flow_manifest(raw)
        if not result.valid or result.manifest is None:
            raise ValueError(f"built-in flow {path.name} is invalid: {'; '.join(result.errors)}")
        manifests.append(result.manifest)
    return manifests


def seed_builtin_flows(registry: Any) -> list[str]:
    """Register built-in flows idempotently.

    A ``(flow_id, version)`` already present is skipped, never overwritten, so a
    user-published version is immutable (reference section 7.1).

    Args:
        registry: A :class:`backend.flows.registry.FlowRegistry`.

    Returns:
        ``"<id>@<version>"`` for each flow newly registered.
    """
    seeded: list[str] = []
    for manifest in load_builtin_flows():
        existing = registry.list_flows(flow_id=manifest.id)
        if any(item.version == manifest.version for item in existing):
            continue
        registry.register(manifest)
        seeded.append(f"{manifest.id}@{manifest.version}")
    return seeded


__all__ = ["BUILTIN_DIR", "load_builtin_flows", "seed_builtin_flows"]
