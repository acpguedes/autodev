"""Durable, versioned registry of flow definitions.

Stores every registered ``flow.yaml`` manifest keyed by ``(flow_id, version)``
in the platform state store (SQLite locally, PostgreSQL in production), and
resolves SemVer ranges to the highest matching registered version — the same
conventions as the Agent Registry (E2-S2).
"""

from __future__ import annotations

import json
from typing import Any

from packaging.version import Version

from backend.flows.manifest import validate_flow_manifest
from backend.flows.model import FlowManifest, version_in_range
from backend.persistence.database import get_store


class FlowRegistry:
    """Durable registry of flow definitions backed by the persistence store."""

    def __init__(self, store: Any | None = None) -> None:
        """Initialize the registry, ensuring its backing schema exists.

        Args:
            store: Durable store to use; defaults to the process-wide store
                from :func:`backend.persistence.database.get_store`.

        Raises:
            TypeError: If ``store`` does not expose a ``connect()`` method.
        """
        self._store = store or get_store()
        if not hasattr(self._store, "connect"):
            raise TypeError("FlowRegistry requires a durable store with connect()")
        self._ensure_schema()

    def register(self, manifest: FlowManifest) -> FlowManifest:
        """Insert or update a flow definition registration.

        Args:
            manifest: Validated flow manifest to register.

        Returns:
            The registered manifest, unchanged.
        """
        if self._is_postgres:
            sql = """
                INSERT INTO flow_registry (flow_id, version, manifest_json, updated_at)
                VALUES (%s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT(flow_id, version) DO UPDATE SET
                    manifest_json = EXCLUDED.manifest_json,
                    updated_at = CURRENT_TIMESTAMP
            """
        else:
            sql = """
                INSERT INTO flow_registry (flow_id, version, manifest_json, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(flow_id, version) DO UPDATE SET
                    manifest_json = excluded.manifest_json,
                    updated_at = CURRENT_TIMESTAMP
            """
        with self._store.connect() as conn:
            conn.execute(sql, (manifest.id, manifest.version, json.dumps(manifest.raw)))
            conn.commit()
        return manifest

    def register_raw(self, raw: dict[str, Any]) -> FlowManifest:
        """Validate and register a raw manifest document.

        Args:
            raw: Parsed ``flow.yaml`` document.

        Returns:
            The validated, registered :class:`FlowManifest`.

        Raises:
            ValueError: If the document fails validation.
        """
        result = validate_flow_manifest(raw)
        if not result.valid or result.manifest is None:
            raise ValueError("; ".join(result.errors))
        return self.register(result.manifest)

    def resolve(self, flow_id: str, version_range: str = "*") -> FlowManifest:
        """Resolve the highest registered version of a flow matching a range.

        Args:
            flow_id: Fully qualified flow id in ``namespace/name`` format.
            version_range: SemVer range expression, or ``"*"`` for any version.

        Returns:
            The highest-versioned matching :class:`FlowManifest`.

        Raises:
            KeyError: If no registered version satisfies the range.
        """
        matches = [
            manifest
            for manifest in self.list_flows(flow_id=flow_id)
            if version_in_range(manifest.version, version_range)
        ]
        if not matches:
            raise KeyError(f"No flow {flow_id!r} matches {version_range!r}")
        return sorted(matches, key=lambda m: Version(m.version), reverse=True)[0]

    def list_flows(self, *, flow_id: str | None = None) -> list[FlowManifest]:
        """List registered flow definitions.

        Args:
            flow_id: Restrict to a single flow id when given.

        Returns:
            Validated manifests, ordered by flow id then version.
        """
        placeholder = "%s" if self._is_postgres else "?"
        base = "SELECT manifest_json FROM flow_registry"
        with self._store.connect() as conn:
            if flow_id is None:
                rows = conn.execute(f"{base} ORDER BY flow_id, version").fetchall()
            else:
                rows = conn.execute(
                    f"{base} WHERE flow_id = {placeholder} ORDER BY version",
                    (flow_id,),
                ).fetchall()
        manifests: list[FlowManifest] = []
        for row in rows:
            raw = row[0] if not hasattr(row, "keys") else row["manifest_json"]
            document = raw if isinstance(raw, dict) else json.loads(raw)
            result = validate_flow_manifest(document)
            if result.valid and result.manifest is not None:
                manifests.append(result.manifest)
        return manifests

    def catalog(self) -> dict[str, Any]:
        """Render the registry as a JSON-serializable catalog document.

        Returns:
            A catalog dict with ``schemaVersion`` and one item per registered
            flow version.
        """
        return {
            "schemaVersion": "1",
            "flows": [
                {
                    "id": manifest.id,
                    "version": manifest.version,
                    "name": manifest.name,
                    "description": manifest.description,
                    "hostApi": manifest.host_api,
                    "triggers": [
                        {
                            "type": trigger.type,
                            "on": trigger.on,
                            "schedule": trigger.schedule,
                        }
                        for trigger in manifest.triggers
                    ],
                    "nodes": len(manifest.nodes),
                }
                for manifest in self.list_flows()
            ],
        }

    @property
    def _is_postgres(self) -> bool:
        """Whether the backing store is a PostgreSQL database."""
        url = str(getattr(self._store, "database_url", ""))
        return url.startswith(("postgresql://", "postgres://"))

    def _ensure_schema(self) -> None:
        """Create the ``flow_registry`` table if it does not exist."""
        if self._is_postgres:
            sql = """
                CREATE TABLE IF NOT EXISTS flow_registry (
                    flow_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    manifest_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(flow_id, version)
                )
            """
        else:
            sql = """
                CREATE TABLE IF NOT EXISTS flow_registry (
                    flow_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(flow_id, version)
                )
            """
        with self._store.connect() as conn:
            conn.execute(sql)
            conn.commit()


__all__ = ["FlowRegistry"]
