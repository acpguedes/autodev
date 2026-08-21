"""Durable Skill Registry with SemVer resolution and trigger search (E6-S2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.version import Version

from backend.persistence.database import get_store
from backend.plugins.registry_core import VersionedExtensionRegistryCore
from backend.skills.manifest import SkillManifest, validate_manifest as validate_skill_manifest

SKILL_REGISTRY_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class SkillRef:
    """A registered skill version and its resolved manifest.

    Attributes:
        skill_id: Fully qualified skill id in ``namespace/name`` format.
        version: SemVer version of this registration.
        plugin_id: Identifier of the plugin that registered the skill.
        manifest: Parsed skill manifest.
        deprecated: Whether this version has been deprecated.
        deprecation_reason: Human-readable deprecation reason, if any.
    """

    skill_id: str
    version: str
    plugin_id: str
    manifest: SkillManifest
    deprecated: bool = False
    deprecation_reason: str = ""

    @property
    def id(self) -> str:
        """Alias for :attr:`skill_id`."""
        return self.skill_id

    def to_catalog_item(self) -> dict[str, Any]:
        """Render this reference as a catalog entry for API responses.

        Returns:
            A JSON-serializable dict describing the skill registration.
        """
        return {
            "id": self.skill_id,
            "version": self.version,
            "pluginId": self.plugin_id,
            "kind": self.manifest.kind,
            "deprecated": self.deprecated,
            "deprecationReason": self.deprecation_reason,
            "triggers": list(self.manifest.triggers),
            "permissions": {
                "filesystem": self.manifest.permissions.filesystem,
                "network": self.manifest.permissions.network,
                "sandbox": self.manifest.permissions.sandbox,
            },
        }


class SkillRegistry:
    """Durable registry of skill versions backed by the persistence store."""

    def __init__(self, store: Any | None = None) -> None:
        """Initialize the registry, ensuring its backing schema exists.

        Args:
            store: Durable store to use; defaults to the process-wide store from
                :func:`backend.persistence.database.get_store`.

        Raises:
            TypeError: If ``store`` does not expose a ``connect()`` method.
        """
        self._store = store or get_store()
        if not hasattr(self._store, "connect"):
            raise TypeError("SkillRegistry requires a durable store with connect()")
        self._core: VersionedExtensionRegistryCore[SkillRef, SkillManifest] = (
            VersionedExtensionRegistryCore(
                self._store,
                table="skill_registry",
                id_column="skill_id",
                kind="skill",
                schema_version=SKILL_REGISTRY_SCHEMA_VERSION,
                catalog_key="skills",
                decode_ref=self._decode_ref,
            )
        )

    def register(self, manifest: SkillManifest, *, plugin_id: str) -> SkillRef:
        """Insert or update a registration for a skill manifest.

        Args:
            manifest: Skill manifest to register.
            plugin_id: Identifier of the plugin providing the skill.

        Returns:
            The resulting :class:`SkillRef`.
        """
        self._core.upsert(manifest, plugin_id=plugin_id)
        return SkillRef(manifest.id, manifest.version, plugin_id, manifest)

    def resolve(self, skill_id: str, version_range: str = "*") -> SkillRef:
        """Resolve the highest registered version of a skill matching a range.

        Args:
            skill_id: Fully qualified skill id.
            version_range: SemVer range expression, or ``"*"`` for any version.

        Returns:
            The highest-versioned matching :class:`SkillRef`.

        Raises:
            KeyError: If no registered version satisfies the range.
        """
        return self._core.resolve(skill_id, version_range)

    def find_by_trigger(self, trigger: str) -> list[SkillRef]:
        """Find registered skills that declare a given trigger.

        Args:
            trigger: Trigger identifier to search for.

        Returns:
            Matching skill references, sorted by id then descending version.
        """
        matches = [ref for ref in self.list_skills() if trigger in ref.manifest.triggers]
        return sorted(matches, key=lambda ref: (ref.skill_id, Version(ref.version)), reverse=True)

    def deprecate(self, skill_id: str, version: str, reason: str) -> None:
        """Mark a specific skill version as deprecated and emit a plugin event.

        Args:
            skill_id: Fully qualified skill id.
            version: Exact SemVer version to deprecate.
            reason: Human-readable deprecation reason.
        """
        self._core.deprecate(skill_id, version, reason)

    def activate(self, skill_id: str, version: str) -> None:
        """Clear the deprecated flag on a specific skill version and emit a plugin event.

        The inverse of :meth:`deprecate`, reusing the same ``deprecated``
        column as the activation signal instead of introducing a second,
        parallel activation store (E16-S4).

        Args:
            skill_id: Fully qualified skill id.
            version: Exact SemVer version to activate.
        """
        self._core.activate(skill_id, version)

    def list_skills(self, *, skill_id: str | None = None) -> list[SkillRef]:
        """List registered skill versions, optionally filtered by skill id.

        Args:
            skill_id: If given, restrict results to this fully qualified skill id.

        Returns:
            Matching skill references, sorted by skill id and descending version.
        """
        return self._core.list_all(ext_id=skill_id)

    def catalog(self, *, trigger: str | None = None) -> dict[str, Any]:
        """Build a JSON-serializable catalog of registered skills.

        Args:
            trigger: If given, restrict the catalog to skills declaring this trigger.

        Returns:
            A dict with ``schemaVersion`` and a ``skills`` catalog item list.
        """
        refs = self.find_by_trigger(trigger) if trigger else self.list_skills()
        return self._core.catalog(refs)

    def sync_from_plugin_store(self) -> None:
        """Register skills declared by every enabled plugin in the plugin store."""
        self._core.sync_from_plugin_store(
            load_manifest=_load_skill_manifest, register=self.register
        )

    def _decode_ref(self, raw: dict[str, Any]) -> SkillRef:
        """Decode one raw, column-keyed row dict into a :class:`SkillRef`.

        Args:
            raw: Column-name-keyed row, as produced by the core's row decoder.

        Returns:
            The decoded skill reference.

        Raises:
            ValueError: If the stored manifest JSON fails validation.
        """
        manifest_json = raw["manifest_json"]
        if isinstance(manifest_json, str):
            manifest_json = json.loads(manifest_json)
        result = validate_skill_manifest(manifest_json)
        if not result.valid or result.manifest is None:
            raise ValueError("; ".join(result.errors))
        return SkillRef(
            skill_id=raw["skill_id"],
            version=raw["version"],
            plugin_id=raw["plugin_id"],
            manifest=result.manifest,
            deprecated=bool(raw.get("deprecated", 0)),
            deprecation_reason=raw.get("deprecation_reason") or "",
        )


def _load_yaml(path: Path) -> Any:
    """Read and parse a YAML document from disk."""
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_skill_manifest(path: Path) -> SkillManifest | None:
    """Load and validate a skill manifest from a plugin extension point path.

    Returns ``None`` (instead of raising) on an invalid manifest, so
    :meth:`SkillRegistry.sync_from_plugin_store` skips it exactly as before.
    """
    result = validate_skill_manifest(_load_yaml(path))
    if not result.valid or result.manifest is None:
        return None
    return result.manifest


__all__ = ["SKILL_REGISTRY_SCHEMA_VERSION", "SkillRef", "SkillRegistry"]
