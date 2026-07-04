"""Plugin Host discovery and lifecycle state machine."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from backend.persistence.database import get_store
from backend.plugins.events import PluginEvent
from backend.plugins.manifest import PluginManifest, load_manifest
from backend.plugins.store import PluginStore

HOST_API_VERSION = "2.0.0"


class PluginState(StrEnum):
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNINSTALLED = "uninstalled"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class PluginCandidate:
    path: Path
    manifest_path: Path
    manifest: PluginManifest


@dataclass(frozen=True)
class PluginRecord:
    plugin_id: str
    version: str
    state: PluginState
    manifest_path: Path
    manifest: PluginManifest
    reason: str = ""


@dataclass
class ScopedHostApi:
    manifest: PluginManifest
    extensions: list[dict[str, Any]] = field(default_factory=list)

    def register_extension(self, kind: str, extension_id: str, metadata: dict[str, Any] | None = None) -> None:
        declared = {(point.kind.value, point.id) for point in self.manifest.extension_points}
        if (kind, extension_id) not in declared:
            raise PermissionError(f"extension {kind}:{extension_id} is not declared in plugin.yaml")
        self.extensions.append({"kind": kind, "id": extension_id, "metadata": metadata or {}})


class PluginHost:
    def __init__(
        self,
        *,
        store: Any | None = None,
        plugin_dirs: Iterable[Path | str] = (),
        host_api_version: str = HOST_API_VERSION,
    ) -> None:
        self._store = PluginStore(store or get_store())
        self._plugin_dirs = tuple(Path(path) for path in plugin_dirs)
        self._host_api_version = Version(host_api_version)
        self._loaded: dict[str, ScopedHostApi] = {}

    @property
    def events(self) -> list[PluginEvent]:
        return self._store.list_events()

    def discover(self) -> list[PluginCandidate]:
        candidates: list[PluginCandidate] = []
        seen: set[Path] = set()
        for root in self._plugin_dirs:
            if not root.exists():
                continue
            for manifest_path in sorted(root.glob("*/plugin.yaml")):
                candidate = self._candidate_from_manifest(manifest_path)
                if candidate is not None and candidate.manifest_path not in seen:
                    seen.add(candidate.manifest_path)
                    candidates.append(candidate)
        for manifest_path in self._entry_point_manifests():
            candidate = self._candidate_from_manifest(manifest_path)
            if candidate is not None and candidate.manifest_path not in seen:
                seen.add(candidate.manifest_path)
                candidates.append(candidate)
        return candidates

    def install(self, plugin_path: Path | str) -> PluginRecord:
        candidate = self._candidate_from_manifest(Path(plugin_path) / "plugin.yaml")
        if candidate is None:
            raise ValueError(f"No valid plugin.yaml found under {plugin_path}")
        reason = self._compatibility_reason(candidate.manifest)
        state = PluginState.REJECTED if reason else PluginState.INSTALLED
        record = self._persist(candidate, state=state, reason=reason)
        if state is PluginState.INSTALLED:
            self._emit("plugin.installed", candidate.manifest, {"version": candidate.manifest.version})
        return record

    def enable(self, plugin_id: str) -> PluginRecord:
        record = self.get(plugin_id)
        if record.state not in {PluginState.INSTALLED, PluginState.DISABLED}:
            raise ValueError(f"Cannot enable plugin {plugin_id} from state {record.state.value}")
        try:
            register = self._load_entrypoint(record.manifest, record.manifest_path.parent)
            host_api = ScopedHostApi(record.manifest)
            register(host_api)
        except Exception as exc:  # noqa: BLE001 - failure must be isolated and audited
            return self._transition(record, PluginState.QUARANTINED, reason=str(exc))
        self._loaded[plugin_id] = host_api
        updated = self._transition(record, PluginState.ENABLED)
        self._emit("plugin.enabled", record.manifest, {"extensions": host_api.extensions})
        return updated

    def disable(self, plugin_id: str) -> PluginRecord:
        record = self.get(plugin_id)
        if record.state is not PluginState.ENABLED:
            raise ValueError(f"Cannot disable plugin {plugin_id} from state {record.state.value}")
        self._loaded.pop(plugin_id, None)
        updated = self._transition(record, PluginState.DISABLED)
        self._emit("plugin.disabled", record.manifest, {"version": record.version})
        return updated

    def uninstall(self, plugin_id: str) -> PluginRecord:
        record = self.get(plugin_id)
        if record.state is PluginState.ENABLED:
            record = self.disable(plugin_id)
        updated = self._transition(record, PluginState.UNINSTALLED)
        self._store.delete_plugin(plugin_id)
        return updated

    def get(self, plugin_id: str) -> PluginRecord:
        row = self._store.get_plugin(plugin_id)
        if row is None:
            raise KeyError(plugin_id)
        return self._record_from_row(row)

    def _candidate_from_manifest(self, manifest_path: Path) -> PluginCandidate | None:
        try:
            manifest = load_manifest(manifest_path)
        except Exception:
            return None
        return PluginCandidate(
            path=manifest_path.parent,
            manifest_path=manifest_path,
            manifest=manifest,
        )

    def _entry_point_manifests(self) -> list[Path]:
        manifests: list[Path] = []
        entry_points = importlib.metadata.entry_points(group="autodev.plugins")
        for entry_point in entry_points:
            try:
                value = entry_point.load()
                manifest_path = Path(value() if callable(value) else value)
                manifests.append(manifest_path)
            except Exception:
                continue
        return manifests

    def _compatibility_reason(self, manifest: PluginManifest) -> str:
        specifier = SpecifierSet(manifest.host_api.replace(" ", ","))
        if self._host_api_version not in specifier:
            return f"hostApi {manifest.host_api} is incompatible with host {self._host_api_version}"
        return ""

    def _persist(self, candidate: PluginCandidate, *, state: PluginState, reason: str = "") -> PluginRecord:
        self._store.upsert_plugin(
            plugin_id=candidate.manifest.id,
            version=candidate.manifest.version,
            state=state.value,
            manifest_path=str(candidate.manifest_path),
            manifest_json=candidate.manifest.raw,
            reason=reason,
        )
        return PluginRecord(
            plugin_id=candidate.manifest.id,
            version=candidate.manifest.version,
            state=state,
            manifest_path=candidate.manifest_path,
            manifest=candidate.manifest,
            reason=reason,
        )

    def _transition(self, record: PluginRecord, state: PluginState, reason: str = "") -> PluginRecord:
        candidate = PluginCandidate(record.manifest_path.parent, record.manifest_path, record.manifest)
        return self._persist(candidate, state=state, reason=reason)

    def _emit(self, name: str, manifest: PluginManifest, payload: dict[str, Any]) -> None:
        self._store.append_event(PluginEvent(name=name, plugin_id=manifest.id, payload=payload))

    def _record_from_row(self, row: dict[str, Any]) -> PluginRecord:
        manifest = load_manifest(row["manifest_path"])
        return PluginRecord(
            plugin_id=row["id"],
            version=row["version"],
            state=PluginState(row["state"]),
            manifest_path=Path(row["manifest_path"]),
            manifest=manifest,
            reason=row["reason"],
        )

    def _load_entrypoint(self, manifest: PluginManifest, plugin_dir: Path) -> Callable[[ScopedHostApi], None]:
        if manifest.runtime.loader != "in-process":
            raise ValueError(f"runtime.loader {manifest.runtime.loader} is not supported by the E1-S2 host")
        module_name, function_name = manifest.runtime.entrypoint.split(":", 1)
        module = self._load_module(module_name, plugin_dir)
        register = getattr(module, function_name)
        if not callable(register):
            raise TypeError(f"{manifest.runtime.entrypoint} is not callable")
        return register

    def _load_module(self, module_name: str, plugin_dir: Path) -> ModuleType:
        module_file = plugin_dir / f"{module_name.rsplit('.', 1)[-1]}.py"
        if module_file.exists():
            spec = importlib.util.spec_from_file_location(f"_autodev_plugin_{module_name}", module_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot import {module_name} from {module_file}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
        sys.path.insert(0, str(plugin_dir))
        try:
            return importlib.import_module(module_name)
        finally:
            if sys.path[0] == str(plugin_dir):
                sys.path.pop(0)


__all__ = [
    "HOST_API_VERSION",
    "PluginCandidate",
    "PluginHost",
    "PluginRecord",
    "PluginState",
    "ScopedHostApi",
]
