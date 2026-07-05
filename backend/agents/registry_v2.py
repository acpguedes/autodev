"""Durable v2 Agent Registry with SemVer resolution and capability search."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from backend.agents.manifest import AgentManifest, load_agent_manifest, validate_agent_manifest
from backend.persistence.database import get_store
from backend.plugins.events import PluginEvent
from backend.plugins.manifest import validate_manifest as validate_plugin_manifest
from backend.plugins.store import PluginStore

AGENT_REGISTRY_SCHEMA_VERSION = "2.0"


@dataclass(frozen=True)
class AgentRef:
    """A registered agent version and its resolved manifest.

    Attributes:
        agent_id: Fully qualified agent id in ``namespace/name`` format.
        version: SemVer version of this registration.
        plugin_id: Identifier of the plugin that registered the agent.
        manifest: Parsed agent manifest.
        score: Ranking score used when searching by capability.
        deprecated: Whether this version has been deprecated.
        deprecation_reason: Human-readable deprecation reason, if any.
    """

    agent_id: str
    version: str
    plugin_id: str
    manifest: AgentManifest
    score: float = 0.0
    deprecated: bool = False
    deprecation_reason: str = ""

    @property
    def id(self) -> str:
        """Alias for :attr:`agent_id`."""
        return self.agent_id

    def to_catalog_item(self) -> dict[str, Any]:
        """Render this reference as a catalog entry for API responses.

        Returns:
            A JSON-serializable dict describing the agent registration.
        """
        return {
            "id": self.agent_id,
            "version": self.version,
            "pluginId": self.plugin_id,
            "deprecated": self.deprecated,
            "deprecationReason": self.deprecation_reason,
            "capabilities": [
                {"id": capability.id, "version": capability.version, "level": capability.level}
                for capability in self.manifest.capabilities
            ],
            "io": {
                "contract": self.manifest.io.contract,
                "contractVersion": self.manifest.io.contract_version,
            },
            "rank": {"score": self.score},
        }


class AgentRegistry:
    """Durable registry of agent versions backed by the persistence store."""

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
            raise TypeError("AgentRegistry requires a durable store with connect()")
        self._plugin_store = PluginStore(self._store)
        self._ensure_schema()

    def register(self, manifest: AgentManifest, *, plugin_id: str) -> AgentRef:
        """Insert or update a registration for an agent manifest.

        Args:
            manifest: Agent manifest to register.
            plugin_id: Identifier of the plugin providing the agent.

        Returns:
            The resulting :class:`AgentRef`.
        """
        sql = self._upsert_sql
        params = self._upsert_params(manifest, plugin_id)
        with self._store.connect() as conn:
            conn.execute(sql, params)
            conn.commit()
        return AgentRef(manifest.id, manifest.version, plugin_id, manifest)

    def resolve(self, agent_id: str, version_range: str = "*") -> AgentRef:
        """Resolve the highest registered version of an agent matching a range.

        Args:
            agent_id: Fully qualified agent id.
            version_range: SemVer range expression, or ``"*"`` for any version.

        Returns:
            The highest-versioned matching :class:`AgentRef`.

        Raises:
            KeyError: If no registered version satisfies the range.
        """
        matches = [
            ref for ref in self.list_agents(agent_id=agent_id)
            if _version_matches(ref.version, version_range)
        ]
        if not matches:
            raise KeyError(f"No agent {agent_id!r} matches {version_range!r}")
        return sorted(matches, key=lambda ref: Version(ref.version), reverse=True)[0]

    def find_by_capability(self, capability: str) -> list[AgentRef]:
        """Find and rank registered agents that declare a given capability.

        Args:
            capability: Dotted capability identifier to search for.

        Returns:
            Matching agent references, sorted by descending score.
        """
        candidates: list[AgentRef] = []
        for ref in self.list_agents():
            for item in ref.manifest.capabilities:
                if item.id != capability:
                    continue
                level_bonus = 100.0 if item.level == "primary" else 50.0
                version_bonus = float(Version(ref.version).major)
                candidates.append(
                    AgentRef(
                        ref.agent_id,
                        ref.version,
                        ref.plugin_id,
                        ref.manifest,
                        score=level_bonus + version_bonus,
                        deprecated=ref.deprecated,
                        deprecation_reason=ref.deprecation_reason,
                    )
                )
                break
        return sorted(candidates, key=lambda ref: (ref.score, Version(ref.version), ref.agent_id), reverse=True)

    def deprecate(self, agent_id: str, version: str, reason: str) -> None:
        """Mark a specific agent version as deprecated and emit a plugin event.

        Args:
            agent_id: Fully qualified agent id.
            version: Exact SemVer version to deprecate.
            reason: Human-readable deprecation reason.
        """
        placeholder = "%s" if self._is_postgres else "?"
        with self._store.connect() as conn:
            conn.execute(
                f"""
                UPDATE agent_registry
                SET deprecated = 1, deprecation_reason = {placeholder}, updated_at = CURRENT_TIMESTAMP
                WHERE agent_id = {placeholder} AND version = {placeholder}
                """,
                (reason, agent_id, version),
            )
            conn.commit()
        self._plugin_store.append_event(
            PluginEvent(
                name="agent.version.deprecated",
                plugin_id=agent_id,
                payload={"version": version, "reason": reason},
            )
        )

    def list_agents(self, *, agent_id: str | None = None) -> list[AgentRef]:
        """List registered agent versions, optionally filtered by agent id.

        Args:
            agent_id: If given, restrict results to this fully qualified agent id.

        Returns:
            Matching agent references, sorted by agent id and descending version.
        """
        where = ""
        params: tuple[Any, ...] = ()
        if agent_id is not None:
            placeholder = "%s" if self._is_postgres else "?"
            where = f" WHERE agent_id = {placeholder}"
            params = (agent_id,)
        with self._store.connect() as conn:
            rows = conn.execute(f"SELECT * FROM agent_registry{where}", params).fetchall()
        refs = [self._decode_ref(row) for row in rows]
        return sorted(refs, key=lambda ref: (ref.agent_id, Version(ref.version)), reverse=True)

    def catalog(self, *, capability: str | None = None) -> dict[str, Any]:
        """Build a JSON-serializable catalog of registered agents.

        Args:
            capability: If given, restrict the catalog to agents declaring this
                capability, ranked by score.

        Returns:
            A dict with ``schemaVersion`` and an ``agents`` catalog item list.
        """
        refs = self.find_by_capability(capability) if capability else self.list_agents()
        return {
            "schemaVersion": AGENT_REGISTRY_SCHEMA_VERSION,
            "agents": [ref.to_catalog_item() for ref in refs],
        }

    def sync_from_plugin_store(self) -> None:
        """Register agents declared by every enabled plugin in the plugin store."""
        for row in self._plugin_store.list_plugins():
            if row["state"] != "enabled":
                continue
            result = validate_plugin_manifest(row["manifest_json"])
            if not result.valid or result.manifest is None:
                continue
            plugin_manifest = result.manifest
            plugin_root = Path(row["manifest_path"]).parent
            for point in plugin_manifest.extension_points:
                if point.kind.value != "agent" or not point.manifest:
                    continue
                agent_manifest = load_agent_manifest(plugin_root / point.manifest)
                self.register(agent_manifest, plugin_id=plugin_manifest.id)

    def _ensure_schema(self) -> None:
        """Create the ``agent_registry`` table and index if they do not exist."""
        if self._is_postgres:
            sql = """
                CREATE TABLE IF NOT EXISTS agent_registry (
                    agent_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    plugin_id TEXT NOT NULL,
                    manifest_json JSONB NOT NULL,
                    deprecated INTEGER NOT NULL DEFAULT 0,
                    deprecation_reason TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(agent_id, version)
                )
            """
            index_sql = "CREATE INDEX IF NOT EXISTS idx_pg_agent_registry_plugin ON agent_registry(plugin_id)"
        else:
            sql = """
                CREATE TABLE IF NOT EXISTS agent_registry (
                    agent_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    plugin_id TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    deprecated INTEGER NOT NULL DEFAULT 0,
                    deprecation_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(agent_id, version)
                )
            """
            index_sql = "CREATE INDEX IF NOT EXISTS idx_agent_registry_plugin ON agent_registry(plugin_id)"
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
        """The dialect-appropriate upsert statement for ``agent_registry``."""
        if self._is_postgres:
            return """
                INSERT INTO agent_registry (agent_id, version, plugin_id, manifest_json, deprecated, deprecation_reason, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, 0, '', CURRENT_TIMESTAMP)
                ON CONFLICT(agent_id, version) DO UPDATE SET
                    plugin_id = EXCLUDED.plugin_id,
                    manifest_json = EXCLUDED.manifest_json,
                    updated_at = CURRENT_TIMESTAMP
            """
        return """
            INSERT INTO agent_registry (agent_id, version, plugin_id, manifest_json, deprecated, deprecation_reason, updated_at)
            VALUES (?, ?, ?, ?, 0, '', CURRENT_TIMESTAMP)
            ON CONFLICT(agent_id, version) DO UPDATE SET
                plugin_id = excluded.plugin_id,
                manifest_json = excluded.manifest_json,
                updated_at = CURRENT_TIMESTAMP
        """

    def _upsert_params(self, manifest: AgentManifest, plugin_id: str) -> tuple[Any, ...]:
        """Build the parameter tuple for the upsert statement.

        Args:
            manifest: Agent manifest being registered.
            plugin_id: Identifier of the plugin providing the agent.

        Returns:
            Parameters matching the placeholders in :attr:`_upsert_sql`.
        """
        return (manifest.id, manifest.version, plugin_id, json.dumps(manifest.raw))

    def _decode_ref(self, row: Any) -> AgentRef:
        """Decode a database row into an :class:`AgentRef`.

        Args:
            row: Row returned by the store, either mapping-like or a plain tuple.

        Returns:
            The decoded agent reference.

        Raises:
            ValueError: If the stored manifest JSON fails validation.
        """
        if hasattr(row, "keys"):
            raw = {key: row[key] for key in row.keys()}
        else:
            columns = (
                "agent_id",
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
        result = validate_agent_manifest(manifest_json)
        if not result.valid or result.manifest is None:
            raise ValueError("; ".join(result.errors))
        return AgentRef(
            agent_id=raw["agent_id"],
            version=raw["version"],
            plugin_id=raw["plugin_id"],
            manifest=result.manifest,
            deprecated=bool(raw.get("deprecated", 0)),
            deprecation_reason=raw.get("deprecation_reason") or "",
        )


def _version_matches(version: str, version_range: str) -> bool:
    """Check whether a version satisfies a SemVer range expression.

    Args:
        version: Exact SemVer version to test.
        version_range: Range expression, or ``""``/``"*"`` for any version.

    Returns:
        ``True`` if ``version`` satisfies ``version_range``.
    """
    if version_range in ("", "*"):
        return True
    return Version(version) in SpecifierSet(version_range.replace(" ", ","))


__all__ = ["AGENT_REGISTRY_SCHEMA_VERSION", "AgentRef", "AgentRegistry"]
