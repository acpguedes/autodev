"""Lightweight plugin lifecycle event records.

E9 will provide the platform Event Bus. Until then, E1 persists and exposes the
same event names from the plugin store so lifecycle transitions are auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PluginEvent:
    name: str
    plugin_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


__all__ = ["PluginEvent"]
