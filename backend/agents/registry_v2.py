"""Durable v2 Agent Registry with SemVer resolution and capability search."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from packaging.version import Version

from backend.agents.manifest import AgentManifest, load_agent_manifest, validate_agent_manifest
from backend.persistence.database import get_store
from backend.plugins.registry_core import VersionedExtensionRegistryCore

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
        self._core: VersionedExtensionRegistryCore[AgentRef, AgentManifest] = (
            VersionedExtensionRegistryCore(
                self._store,
                table="agent_registry",
                id_column="agent_id",
                kind="agent",
                schema_version=AGENT_REGISTRY_SCHEMA_VERSION,
                catalog_key="agents",
                decode_ref=self._decode_ref,
            )
        )

    def register(self, manifest: AgentManifest, *, plugin_id: str) -> AgentRef:
        """Insert or update a registration for an agent manifest.

        Args:
            manifest: Agent manifest to register.
            plugin_id: Identifier of the plugin providing the agent.

        Returns:
            The resulting :class:`AgentRef`.
        """
        self._core.upsert(manifest, plugin_id=plugin_id)
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
        return self._core.resolve(agent_id, version_range)

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
        self._core.deprecate(agent_id, version, reason)

    def activate(self, agent_id: str, version: str) -> None:
        """Clear the deprecated flag on a specific agent version and emit a plugin event.

        The inverse of :meth:`deprecate`, reusing the same ``deprecated``
        column as the activation signal instead of introducing a second,
        parallel activation store (E16-S4).

        Args:
            agent_id: Fully qualified agent id.
            version: Exact SemVer version to activate.
        """
        self._core.activate(agent_id, version)

    def list_agents(self, *, agent_id: str | None = None) -> list[AgentRef]:
        """List registered agent versions, optionally filtered by agent id.

        Args:
            agent_id: If given, restrict results to this fully qualified agent id.

        Returns:
            Matching agent references, sorted by agent id and descending version.
        """
        return self._core.list_all(ext_id=agent_id)

    def catalog(self, *, capability: str | None = None) -> dict[str, Any]:
        """Build a JSON-serializable catalog of registered agents.

        Args:
            capability: If given, restrict the catalog to agents declaring this
                capability, ranked by score.

        Returns:
            A dict with ``schemaVersion`` and an ``agents`` catalog item list.
        """
        refs = self.find_by_capability(capability) if capability else self.list_agents()
        return self._core.catalog(refs)

    def sync_from_plugin_store(self) -> None:
        """Register agents declared by every enabled plugin in the plugin store."""
        self._core.sync_from_plugin_store(
            load_manifest=load_agent_manifest, register=self.register
        )

    def _decode_ref(self, raw: dict[str, Any]) -> AgentRef:
        """Decode one raw, column-keyed row dict into an :class:`AgentRef`.

        Args:
            raw: Column-name-keyed row, as produced by the core's row decoder.

        Returns:
            The decoded agent reference.

        Raises:
            ValueError: If the stored manifest JSON fails validation.
        """
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


__all__ = ["AGENT_REGISTRY_SCHEMA_VERSION", "AgentRef", "AgentRegistry"]
