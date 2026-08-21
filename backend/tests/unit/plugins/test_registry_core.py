"""Tests for the shared versioned-extension-registry core (E47-S3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from backend.agents.registry_v2 import AgentRegistry
from backend.persistence.database import DurableStore
from backend.plugins.registry_core import VersionedExtensionRegistryCore, version_matches
from backend.skills.registry_v2 import SkillRegistry


def test_agent_and_skill_registries_delegate_to_the_shared_core(tmp_path: Path) -> None:
    """The consolidation actually happened: both registries own the same core type."""
    store = DurableStore(f"sqlite:///{tmp_path / 'shared_core.db'}")
    agent_registry = AgentRegistry(store)
    skill_registry = SkillRegistry(store)

    assert isinstance(agent_registry._core, VersionedExtensionRegistryCore)
    assert isinstance(skill_registry._core, VersionedExtensionRegistryCore)
    assert type(agent_registry._core) is type(skill_registry._core)


@pytest.mark.parametrize(
    ("version", "version_range", "expected"),
    [
        ("1.0.0", "*", True),
        ("1.0.0", "", True),
        ("1.0.0", ">=1.0.0,<2.0.0", True),
        ("2.0.0", ">=1.0.0,<2.0.0", False),
    ],
)
def test_version_matches(version: str, version_range: str, expected: bool) -> None:
    assert version_matches(version, version_range) is expected


@dataclass(frozen=True)
class _WidgetManifest:
    """Minimal stand-in manifest shaped like the core's ``ManifestT`` contract."""

    id: str
    version: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class _WidgetRef:
    """Minimal stand-in ref shaped like the core's ``RefT`` contract."""

    widget_id: str
    version: str
    plugin_id: str
    deprecated: bool = False
    deprecation_reason: str = ""

    @property
    def id(self) -> str:
        return self.widget_id

    def to_catalog_item(self) -> dict[str, Any]:
        return {"id": self.widget_id, "version": self.version, "deprecated": self.deprecated}


def _decode_widget(raw: dict[str, Any]) -> _WidgetRef:
    return _WidgetRef(
        widget_id=raw["widget_id"],
        version=raw["version"],
        plugin_id=raw["plugin_id"],
        deprecated=bool(raw.get("deprecated", 0)),
        deprecation_reason=raw.get("deprecation_reason") or "",
    )


@pytest.fixture()
def widget_core(tmp_path: Path) -> VersionedExtensionRegistryCore[_WidgetRef, _WidgetManifest]:
    """A core instance over a throwaway ``widget_registry`` table.

    Exercises the core in isolation from both concrete registries, proving its
    register/resolve/deprecate/activate/catalog/list semantics are generic and
    do not depend on agent- or skill-specific manifest shapes.
    """
    store = DurableStore(f"sqlite:///{tmp_path / 'widgets.db'}")
    return VersionedExtensionRegistryCore(
        store,
        table="widget_registry",
        id_column="widget_id",
        kind="widget",
        schema_version="9",
        catalog_key="widgets",
        decode_ref=_decode_widget,
    )


def test_core_register_resolve_and_list(
    widget_core: VersionedExtensionRegistryCore[_WidgetRef, _WidgetManifest],
) -> None:
    widget_core.upsert(_WidgetManifest("acme/gizmo", "1.0.0", {}), plugin_id="acme/plugin")
    widget_core.upsert(_WidgetManifest("acme/gizmo", "2.0.0", {}), plugin_id="acme/plugin")

    resolved = widget_core.resolve("acme/gizmo", "*")
    assert resolved.version == "2.0.0"

    listed = widget_core.list_all(ext_id="acme/gizmo")
    assert [ref.version for ref in listed] == ["2.0.0", "1.0.0"]


def test_core_resolve_unknown_raises_with_kind_in_message(
    widget_core: VersionedExtensionRegistryCore[_WidgetRef, _WidgetManifest],
) -> None:
    with pytest.raises(KeyError, match="No widget 'acme/missing' matches"):
        widget_core.resolve("acme/missing", "*")


def test_core_deprecate_then_activate_round_trip(
    widget_core: VersionedExtensionRegistryCore[_WidgetRef, _WidgetManifest],
) -> None:
    widget_core.upsert(_WidgetManifest("acme/gizmo", "1.0.0", {}), plugin_id="acme/plugin")

    widget_core.deprecate("acme/gizmo", "1.0.0", "no longer maintained")
    assert widget_core.resolve("acme/gizmo", "*").deprecated is True

    widget_core.activate("acme/gizmo", "1.0.0")
    ref = widget_core.resolve("acme/gizmo", "*")
    assert ref.deprecated is False
    assert ref.deprecation_reason == ""


def test_core_catalog_renders_schema_version_and_catalog_key(
    widget_core: VersionedExtensionRegistryCore[_WidgetRef, _WidgetManifest],
) -> None:
    widget_core.upsert(_WidgetManifest("acme/gizmo", "1.0.0", {}), plugin_id="acme/plugin")

    catalog = widget_core.catalog(widget_core.list_all())

    assert catalog["schemaVersion"] == "9"
    assert catalog["widgets"] == [{"id": "acme/gizmo", "version": "1.0.0", "deprecated": False}]


def test_core_sync_from_plugin_store_is_a_noop_with_no_registered_plugins(
    widget_core: VersionedExtensionRegistryCore[_WidgetRef, _WidgetManifest],
) -> None:
    """No enabled plugins means no extension points, means the loader never runs."""
    calls: list[str] = []
    widget_core.sync_from_plugin_store(
        load_manifest=lambda path: None,
        register=lambda manifest, *, plugin_id: calls.append(plugin_id),
    )
    assert calls == []
