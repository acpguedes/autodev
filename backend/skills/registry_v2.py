"""Durable Skill Registry with SemVer resolution and trigger search (E6-S2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from backend.persistence.database import get_store
from backend.plugins.events import PluginEvent
from backend.plugins.manifest import validate_manifest as validate_plugin_manifest
from backend.plugins.store import PluginStore
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
        self._plugin_store = PluginStore(self._store)
        self._ensure_schema()

    def register(self, manifest: SkillManifest, *, plugin_id: str) -> SkillRef:
        """Insert or update a registration for a skill manifest.

        Args:
            manifest: Skill manifest to register.
            plugin_id: Identifier of the plugin providing the skill.

        Returns:
            The resulting :class:`SkillRef`.
        """
        with self._store.connect() as conn:
            conn.execute(self._upsert_sql, self._upsert_params(manifest, plugin_id))
            conn.commit()
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
        matches = [
            ref for ref in self.list_skills(skill_id=skill_id)
            if _version_matches(ref.version, version_range)
        ]
        if not matches:
            raise KeyError(f"No skill {skill_id!r} matches {version_range!r}")
        return sorted(matches, key=lambda ref: Version(ref.version), reverse=True)[0]

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
        placeholder = "%s" if self._is_postgres else "?"
        with self._store.connect() as conn:
            conn.execute(
                f"""
                UPDATE skill_registry
                SET deprecated = 1, deprecation_reason = {placeholder}, updated_at = CURRENT_TIMESTAMP
                WHERE skill_id = {placeholder} AND version = {placeholder}
                """,
                (reason, skill_id, version),
            )
            conn.commit()
        self._plugin_store.append_event(
            PluginEvent(
                name="skill.version.deprecated",
                plugin_id=skill_id,
                payload={"version": version, "reason": reason},
            )
        )

    def list_skills(self, *, skill_id: str | None = None) -> list[SkillRef]:
        """List registered skill versions, optionally filtered by skill id.

        Args:
            skill_id: If given, restrict results to this fully qualified skill id.

        Returns:
            Matching skill references, sorted by skill id and descending version.
        """
        where = ""
        params: tuple[Any, ...] = ()
        if skill_id is not None:
            placeholder = "%s" if self._is_postgres else "?"
            where = f" WHERE skill_id = {placeholder}"
            params = (skill_id,)
        with self._store.connect() as conn:
            rows = conn.execute(f"SELECT * FROM skill_registry{where}", params).fetchall()
        refs = [self._decode_ref(row) for row in rows]
        return sorted(refs, key=lambda ref: (ref.skill_id, Version(ref.version)), reverse=True)

    def catalog(self, *, trigger: str | None = None) -> dict[str, Any]:
        """Build a JSON-serializable catalog of registered skills.

        Args:
            trigger: If given, restrict the catalog to skills declaring this trigger.

        Returns:
            A dict with ``schemaVersion`` and a ``skills`` catalog item list.
        """
        refs = self.find_by_trigger(trigger) if trigger else self.list_skills()
        return {
            "schemaVersion": SKILL_REGISTRY_SCHEMA_VERSION,
            "skills": [ref.to_catalog_item() for ref in refs],
        }

    def sync_from_plugin_store(self) -> None:
        """Register skills declared by every enabled plugin in the plugin store."""
        for row in self._plugin_store.list_plugins():
            if row["state"] != "enabled":
                continue
            result = validate_plugin_manifest(row["manifest_json"])
            if not result.valid or result.manifest is None:
                continue
            plugin_manifest = result.manifest
            plugin_root = Path(row["manifest_path"]).parent
            for point in plugin_manifest.extension_points:
                if point.kind.value != "skill" or not point.manifest:
                    continue
                raw = _load_yaml(plugin_root / point.manifest)
                skill_result = validate_skill_manifest(raw)
                if not skill_result.valid or skill_result.manifest is None:
                    continue
                self.register(skill_result.manifest, plugin_id=plugin_manifest.id)

    def _ensure_schema(self) -> None:
        """Create the ``skill_registry`` table and index if they do not exist."""
        if self._is_postgres:
            sql = """
                CREATE TABLE IF NOT EXISTS skill_registry (
                    skill_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    plugin_id TEXT NOT NULL,
                    manifest_json JSONB NOT NULL,
                    deprecated INTEGER NOT NULL DEFAULT 0,
                    deprecation_reason TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(skill_id, version)
                )
            """
            index_sql = "CREATE INDEX IF NOT EXISTS idx_pg_skill_registry_plugin ON skill_registry(plugin_id)"
        else:
            sql = """
                CREATE TABLE IF NOT EXISTS skill_registry (
                    skill_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    plugin_id TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    deprecated INTEGER NOT NULL DEFAULT 0,
                    deprecation_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(skill_id, version)
                )
            """
            index_sql = "CREATE INDEX IF NOT EXISTS idx_skill_registry_plugin ON skill_registry(plugin_id)"
        with self._store.connect() as conn:
            conn.execute(sql)
            conn.execute(index_sql)
            conn.commit()

    @property
    def _is_postgres(self) -> bool:
        """Whether the backing store is a PostgreSQL database."""
        return str(getattr(self._store, "database_url", "")).startswith(("postgresql://", "postgres://"))

    @property
    def _upsert_sql(self) -> str:
        """The dialect-appropriate upsert statement for ``skill_registry``."""
        if self._is_postgres:
            return """
                INSERT INTO skill_registry (skill_id, version, plugin_id, manifest_json, deprecated, deprecation_reason, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, 0, '', CURRENT_TIMESTAMP)
                ON CONFLICT(skill_id, version) DO UPDATE SET
                    plugin_id = EXCLUDED.plugin_id,
                    manifest_json = EXCLUDED.manifest_json,
                    updated_at = CURRENT_TIMESTAMP
            """
        return """
            INSERT INTO skill_registry (skill_id, version, plugin_id, manifest_json, deprecated, deprecation_reason, updated_at)
            VALUES (?, ?, ?, ?, 0, '', CURRENT_TIMESTAMP)
            ON CONFLICT(skill_id, version) DO UPDATE SET
                plugin_id = excluded.plugin_id,
                manifest_json = excluded.manifest_json,
                updated_at = CURRENT_TIMESTAMP
        """

    def _upsert_params(self, manifest: SkillManifest, plugin_id: str) -> tuple[Any, ...]:
        """Build the parameter tuple for the upsert statement."""
        return (manifest.id, manifest.version, plugin_id, json.dumps(manifest.raw))

    def _decode_ref(self, row: Any) -> SkillRef:
        """Decode a database row into a :class:`SkillRef`.

        Args:
            row: Row returned by the store, either mapping-like or a plain tuple.

        Returns:
            The decoded skill reference.

        Raises:
            ValueError: If the stored manifest JSON fails validation.
        """
        if hasattr(row, "keys"):
            raw = {key: row[key] for key in row.keys()}
        else:
            columns = (
                "skill_id",
                "version",
                "plugin_id",
                "manifest_json",
                "deprecated",
                "deprecation_reason",
                "created_at",
                "updated_at",
            )
            raw = dict(zip(columns, row))
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


def _version_matches(version: str, version_range: str) -> bool:
    """Check whether a version satisfies a SemVer range expression."""
    if version_range in ("", "*"):
        return True
    return Version(version) in SpecifierSet(version_range.replace(" ", ","))


__all__ = ["SKILL_REGISTRY_SCHEMA_VERSION", "SkillRef", "SkillRegistry"]
