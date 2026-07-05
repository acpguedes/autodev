"""Durable plugin lifecycle repository backed by the platform store."""

from __future__ import annotations

import json
from typing import Any

from backend.plugins.events import PluginEvent


class PluginStore:
    """Persist plugin records and lifecycle events through the E0 store."""

    def __init__(self, store: Any) -> None:
        """Initialize the store over a durable backing store.

        Args:
            store: Durable store exposing ``connect()``.

        Raises:
            TypeError: If ``store`` does not expose a ``connect()`` method.
        """
        if not hasattr(store, "connect"):
            raise TypeError("PluginStore requires a durable store with connect()")
        self._store = store

    def upsert_plugin(
        self,
        *,
        plugin_id: str,
        version: str,
        state: str,
        manifest_path: str,
        manifest_json: dict[str, Any],
        reason: str = "",
    ) -> None:
        """Insert or update a plugin's registration record.

        Args:
            plugin_id: Identifier of the plugin.
            version: SemVer version of the registration.
            state: Lifecycle state value to store.
            manifest_path: Path to the plugin's ``plugin.yaml``.
            manifest_json: Parsed manifest document.
            reason: Human-readable reason for the current state, if any.
        """
        if self._is_postgres:
            sql = """
                INSERT INTO plugins (id, version, state, manifest_path, manifest_json, reason, updated_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    version = EXCLUDED.version,
                    state = EXCLUDED.state,
                    manifest_path = EXCLUDED.manifest_path,
                    manifest_json = EXCLUDED.manifest_json,
                    reason = EXCLUDED.reason,
                    updated_at = CURRENT_TIMESTAMP
            """
            params = (plugin_id, version, state, manifest_path, json.dumps(manifest_json), reason)
        else:
            sql = """
                INSERT INTO plugins (id, version, state, manifest_path, manifest_json, reason, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    version = excluded.version,
                    state = excluded.state,
                    manifest_path = excluded.manifest_path,
                    manifest_json = excluded.manifest_json,
                    reason = excluded.reason,
                    updated_at = CURRENT_TIMESTAMP
            """
            params = (plugin_id, version, state, manifest_path, json.dumps(manifest_json), reason)
        with self._store.connect() as conn:
            conn.execute(sql, params)
            conn.commit()

    def get_plugin(self, plugin_id: str) -> dict[str, Any] | None:
        """Fetch a plugin's registration record, or ``None`` if not registered."""
        placeholder = "%s" if self._is_postgres else "?"
        with self._store.connect() as conn:
            row = conn.execute(
                f"SELECT * FROM plugins WHERE id = {placeholder}",
                (plugin_id,),
            ).fetchone()
        return self._decode_plugin(row)

    def list_plugins(self) -> list[dict[str, Any]]:
        """List all registered plugins, ordered by id."""
        with self._store.connect() as conn:
            rows = conn.execute("SELECT * FROM plugins ORDER BY id ASC").fetchall()
        plugins: list[dict[str, Any]] = []
        for row in rows:
            decoded = self._decode_plugin(row)
            if decoded is not None:
                plugins.append(decoded)
        return plugins

    def delete_plugin(self, plugin_id: str) -> None:
        """Delete a plugin's registration record."""
        placeholder = "%s" if self._is_postgres else "?"
        with self._store.connect() as conn:
            conn.execute(f"DELETE FROM plugins WHERE id = {placeholder}", (plugin_id,))
            conn.commit()

    def append_event(self, event: PluginEvent) -> None:
        """Persist a plugin lifecycle event."""
        if self._is_postgres:
            sql = """
                INSERT INTO plugin_events (event_name, plugin_id, payload_json)
                VALUES (%s, %s, %s::jsonb)
            """
        else:
            sql = """
                INSERT INTO plugin_events (event_name, plugin_id, payload_json)
                VALUES (?, ?, ?)
            """
        with self._store.connect() as conn:
            conn.execute(sql, (event.name, event.plugin_id, json.dumps(event.payload)))
            conn.commit()

    def list_events(self) -> list[PluginEvent]:
        """List all recorded plugin lifecycle events, in insertion order."""
        with self._store.connect() as conn:
            rows = conn.execute(
                "SELECT event_name, plugin_id, payload_json, created_at FROM plugin_events ORDER BY id ASC"
            ).fetchall()
        return [self._decode_event(row) for row in rows]

    @property
    def _is_postgres(self) -> bool:
        """Whether the backing store is a PostgreSQL database."""
        return str(getattr(self._store, "database_url", "")).startswith(("postgresql://", "postgres://"))

    def _decode_plugin(self, row: Any) -> dict[str, Any] | None:
        """Decode a database row into a plugin record dict, or ``None`` if ``row`` is ``None``."""
        if row is None:
            return None
        if isinstance(row, dict):
            raw = row
        elif hasattr(row, "keys"):
            raw = {key: row[key] for key in row.keys()}
        else:
            columns = ("id", "version", "state", "manifest_path", "manifest_json", "reason", "created_at", "updated_at")
            raw = dict(zip(columns, row))
        manifest_json = raw["manifest_json"]
        if isinstance(manifest_json, str):
            manifest_json = json.loads(manifest_json)
        return {
            "id": raw["id"],
            "version": raw["version"],
            "state": raw["state"],
            "manifest_path": raw["manifest_path"],
            "manifest_json": manifest_json,
            "reason": raw.get("reason") or "",
            "created_at": str(raw.get("created_at", "")),
            "updated_at": str(raw.get("updated_at", "")),
        }

    def _decode_event(self, row: Any) -> PluginEvent:
        """Decode a database row into a :class:`PluginEvent`."""
        if hasattr(row, "keys"):
            name = row["event_name"]
            plugin_id = row["plugin_id"]
            payload = row["payload_json"]
            created_at = row["created_at"]
        else:
            name, plugin_id, payload, created_at = row
        if isinstance(payload, str):
            payload = json.loads(payload)
        return PluginEvent(name=name, plugin_id=plugin_id, payload=payload, created_at=str(created_at))


__all__ = ["PluginStore"]
