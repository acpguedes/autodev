"""Active plugin registry projection."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.persistence.database import get_store
from backend.plugins.manifest import validate_manifest
from backend.plugins.store import PluginStore

REGISTRY_SCHEMA_VERSION = "1"


class ActivePluginRegistry:
    def __init__(self, store: Any | None = None) -> None:
        self._store = PluginStore(store or get_store())

    def snapshot(self) -> dict[str, Any]:
        active_plugins: list[dict[str, Any]] = []
        inhabited: dict[str, list[str]] = defaultdict(list)
        for row in self._store.list_plugins():
            if row["state"] != "enabled":
                continue
            result = validate_manifest(row["manifest_json"])
            if not result.valid or result.manifest is None:
                continue
            manifest = result.manifest
            extension_points = [
                {
                    "kind": point.kind.value,
                    "id": point.id,
                    "contract": point.contract,
                }
                for point in manifest.extension_points
            ]
            active_plugins.append(
                {
                    "id": manifest.id,
                    "version": manifest.version,
                    "state": row["state"],
                    "extensionPoints": extension_points,
                }
            )
            for point in manifest.extension_points:
                inhabited[point.kind.value].append(manifest.id)
        return {
            "schemaVersion": REGISTRY_SCHEMA_VERSION,
            "activePlugins": active_plugins,
            "inhabitedExtensionPoints": [
                {"kind": kind, "pluginIds": sorted(plugin_ids)}
                for kind, plugin_ids in sorted(inhabited.items())
            ],
        }


__all__ = ["ActivePluginRegistry", "REGISTRY_SCHEMA_VERSION"]
