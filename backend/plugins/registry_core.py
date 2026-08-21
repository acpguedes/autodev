"""Shared versioned-extension-registry core (E47-S3).

Factors out the methods that were duplicated, near byte-for-byte, between
``backend.agents.registry_v2.AgentRegistry`` and
``backend.skills.registry_v2.SkillRegistry``: schema creation, upsert,
resolve/list, deprecate/activate (with plugin-event emission), catalog
rendering, plugin-store sync, and SemVer range matching.

This is composition, not a generic base class: each concrete registry owns
a :class:`VersionedExtensionRegistryCore` instance and delegates to it,
while keeping its own manifest-format specifics -- ``AgentRegistry`` keeps
``find_by_capability`` and agent-manifest loading; ``SkillRegistry`` keeps
``find_by_trigger`` and YAML loading. A version-resolution or upsert fix now
lands once, for both.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Generic, Sequence, TypeVar

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from backend.plugins.events import PluginEvent
from backend.plugins.manifest import validate_manifest as validate_plugin_manifest
from backend.plugins.store import PluginStore

RefT = TypeVar("RefT")
ManifestT = TypeVar("ManifestT")


def version_matches(version: str, version_range: str) -> bool:
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


class VersionedExtensionRegistryCore(Generic[RefT, ManifestT]):
    """Durable register/resolve/deprecate/activate/catalog core.

    A concrete registry supplies naming (``table``/``id_column``/``kind``),
    a ``decode_ref`` callback that turns one decoded row into its own ``Ref``
    dataclass (running its own manifest validator), and the catalog
    presentation (``schema_version``/``catalog_key``). Every registry backed
    by this core shares one schema-creation, upsert, and version-resolution
    implementation -- a fix can no longer land in only one of them.
    """

    def __init__(
        self,
        store: Any,
        *,
        table: str,
        id_column: str,
        kind: str,
        schema_version: str,
        catalog_key: str,
        decode_ref: Callable[[dict[str, Any]], RefT],
    ) -> None:
        """Initialize the core, ensuring its backing schema exists.

        Args:
            store: Durable store exposing ``connect()``.
            table: Backing table name (e.g. ``"agent_registry"``).
            id_column: Column holding the fully qualified extension id.
            kind: Extension-point kind (``"agent"`` / ``"skill"``); doubles as
                the plugin-event name prefix and the ``sync_from_plugin_store``
                extension-point filter.
            schema_version: ``schemaVersion`` value rendered into catalogs.
            catalog_key: Catalog dict key holding the list of items
                (``"agents"`` / ``"skills"``).
            decode_ref: Turns one decoded row (raw column dict, keyed by the
                actual column names including ``id_column``) into ``RefT``.
        """
        self._store = store
        self._table = table
        self._id_column = id_column
        self._kind = kind
        self._schema_version = schema_version
        self._catalog_key = catalog_key
        self._decode_ref = decode_ref
        self._plugin_store = PluginStore(store)
        self._ensure_schema()

    def upsert(self, manifest: ManifestT, *, plugin_id: str) -> None:
        """Insert or update a registration for a manifest.

        Args:
            manifest: Manifest to register; must expose ``id``, ``version``,
                and ``raw`` (a JSON-serializable document).
            plugin_id: Identifier of the plugin providing the extension.
        """
        with self._store.connect() as conn:
            conn.execute(self._upsert_sql, self._upsert_params(manifest, plugin_id))
            conn.commit()

    def resolve(self, ext_id: str, version_range: str = "*") -> RefT:
        """Resolve the highest registered version matching a SemVer range.

        Args:
            ext_id: Fully qualified extension id.
            version_range: SemVer range expression, or ``"*"`` for any version.

        Returns:
            The highest-versioned matching ``RefT``.

        Raises:
            KeyError: If no registered version satisfies the range.
        """
        matches = [
            ref for ref in self.list_all(ext_id=ext_id)
            if version_matches(ref.version, version_range)  # type: ignore[attr-defined]
        ]
        if not matches:
            raise KeyError(f"No {self._kind} {ext_id!r} matches {version_range!r}")
        return sorted(
            matches, key=lambda ref: Version(ref.version), reverse=True  # type: ignore[attr-defined]
        )[0]

    def deprecate(self, ext_id: str, version: str, reason: str) -> None:
        """Mark a specific version as deprecated and emit a plugin event.

        Args:
            ext_id: Fully qualified extension id.
            version: Exact SemVer version to deprecate.
            reason: Human-readable deprecation reason.
        """
        placeholder = "%s" if self._is_postgres else "?"
        with self._store.connect() as conn:
            conn.execute(
                f"""
                UPDATE {self._table}
                SET deprecated = 1, deprecation_reason = {placeholder}, updated_at = CURRENT_TIMESTAMP
                WHERE {self._id_column} = {placeholder} AND version = {placeholder}
                """,
                (reason, ext_id, version),
            )
            conn.commit()
        self._plugin_store.append_event(
            PluginEvent(
                name=f"{self._kind}.version.deprecated",
                plugin_id=ext_id,
                payload={"version": version, "reason": reason},
            )
        )

    def activate(self, ext_id: str, version: str) -> None:
        """Clear the deprecated flag on a specific version and emit a plugin event.

        The inverse of :meth:`deprecate`, reusing the same ``deprecated``
        column as the activation signal instead of introducing a second,
        parallel activation store (E16-S4).

        Args:
            ext_id: Fully qualified extension id.
            version: Exact SemVer version to activate.
        """
        placeholder = "%s" if self._is_postgres else "?"
        with self._store.connect() as conn:
            conn.execute(
                f"""
                UPDATE {self._table}
                SET deprecated = 0, deprecation_reason = '', updated_at = CURRENT_TIMESTAMP
                WHERE {self._id_column} = {placeholder} AND version = {placeholder}
                """,
                (ext_id, version),
            )
            conn.commit()
        self._plugin_store.append_event(
            PluginEvent(
                name=f"{self._kind}.version.activated",
                plugin_id=ext_id,
                payload={"version": version},
            )
        )

    def list_all(self, *, ext_id: str | None = None) -> list[RefT]:
        """List registered versions, optionally filtered by extension id.

        Args:
            ext_id: If given, restrict results to this fully qualified id.

        Returns:
            Matching references, sorted by id and descending version.
        """
        where = ""
        params: tuple[Any, ...] = ()
        if ext_id is not None:
            placeholder = "%s" if self._is_postgres else "?"
            where = f" WHERE {self._id_column} = {placeholder}"
            params = (ext_id,)
        with self._store.connect() as conn:
            rows = conn.execute(f"SELECT * FROM {self._table}{where}", params).fetchall()
        refs = [self._decode_ref(self._row_to_raw(row)) for row in rows]
        return sorted(
            refs,
            key=lambda ref: (ref.id, Version(ref.version)),  # type: ignore[attr-defined]
            reverse=True,
        )

    def catalog(self, refs: Sequence[RefT]) -> dict[str, Any]:
        """Build a JSON-serializable catalog from already-selected references.

        Args:
            refs: References to render, typically from :meth:`list_all` or a
                registry's own capability/trigger search.

        Returns:
            A dict with ``schemaVersion`` and the type's catalog item list.
        """
        return {
            "schemaVersion": self._schema_version,
            self._catalog_key: [ref.to_catalog_item() for ref in refs],  # type: ignore[attr-defined]
        }

    def sync_from_plugin_store(
        self,
        *,
        load_manifest: Callable[[Path], ManifestT | None],
        register: Callable[..., Any],
    ) -> None:
        """Register extensions declared by every enabled plugin in the plugin store.

        Args:
            load_manifest: Loads (and, if the format requires it, validates)
                the manifest at a path; returning ``None`` skips that point.
                May raise to abort the sync, matching a loader with no
                validate-then-skip step of its own.
            register: The concrete registry's own ``register(manifest, *,
                plugin_id=...)`` method.
        """
        for row in self._plugin_store.list_plugins():
            if row["state"] != "enabled":
                continue
            result = validate_plugin_manifest(row["manifest_json"])
            if not result.valid or result.manifest is None:
                continue
            plugin_manifest = result.manifest
            plugin_root = Path(row["manifest_path"]).parent
            for point in plugin_manifest.extension_points:
                if point.kind.value != self._kind or not point.manifest:
                    continue
                manifest = load_manifest(plugin_root / point.manifest)
                if manifest is None:
                    continue
                register(manifest, plugin_id=plugin_manifest.id)

    def _ensure_schema(self) -> None:
        """Create the backing table and its plugin-id index if absent."""
        if self._is_postgres:
            sql = f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    {self._id_column} TEXT NOT NULL,
                    version TEXT NOT NULL,
                    plugin_id TEXT NOT NULL,
                    manifest_json JSONB NOT NULL,
                    deprecated INTEGER NOT NULL DEFAULT 0,
                    deprecation_reason TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY({self._id_column}, version)
                )
            """
            index_sql = (
                f"CREATE INDEX IF NOT EXISTS idx_pg_{self._table}_plugin "
                f"ON {self._table}(plugin_id)"
            )
        else:
            sql = f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    {self._id_column} TEXT NOT NULL,
                    version TEXT NOT NULL,
                    plugin_id TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    deprecated INTEGER NOT NULL DEFAULT 0,
                    deprecation_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY({self._id_column}, version)
                )
            """
            index_sql = (
                f"CREATE INDEX IF NOT EXISTS idx_{self._table}_plugin "
                f"ON {self._table}(plugin_id)"
            )
        with self._store.connect() as conn:
            conn.execute(sql)
            conn.execute(index_sql)
            conn.commit()

    @property
    def _is_postgres(self) -> bool:
        """Whether the backing store is a PostgreSQL database."""
        return str(getattr(self._store, "database_url", "")).startswith(
            ("postgresql://", "postgres://")
        )

    @property
    def _upsert_sql(self) -> str:
        """The dialect-appropriate upsert statement for this table."""
        if self._is_postgres:
            return f"""
                INSERT INTO {self._table} ({self._id_column}, version, plugin_id, manifest_json, deprecated, deprecation_reason, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, 0, '', CURRENT_TIMESTAMP)
                ON CONFLICT({self._id_column}, version) DO UPDATE SET
                    plugin_id = EXCLUDED.plugin_id,
                    manifest_json = EXCLUDED.manifest_json,
                    updated_at = CURRENT_TIMESTAMP
            """
        return f"""
            INSERT INTO {self._table} ({self._id_column}, version, plugin_id, manifest_json, deprecated, deprecation_reason, updated_at)
            VALUES (?, ?, ?, ?, 0, '', CURRENT_TIMESTAMP)
            ON CONFLICT({self._id_column}, version) DO UPDATE SET
                plugin_id = excluded.plugin_id,
                manifest_json = excluded.manifest_json,
                updated_at = CURRENT_TIMESTAMP
        """

    def _upsert_params(self, manifest: ManifestT, plugin_id: str) -> tuple[Any, ...]:
        """Build the parameter tuple for the upsert statement."""
        import json

        return (
            manifest.id,  # type: ignore[attr-defined]
            manifest.version,  # type: ignore[attr-defined]
            plugin_id,
            json.dumps(manifest.raw),  # type: ignore[attr-defined]
        )

    def _row_to_raw(self, row: Any) -> dict[str, Any]:
        """Normalize one store row into a plain column-name-keyed dict."""
        if hasattr(row, "keys"):
            return {key: row[key] for key in row.keys()}
        columns = (
            self._id_column,
            "plugin_id",
            "manifest_json",
            "deprecated",
            "deprecation_reason",
            "created_at",
            "updated_at",
        )
        return dict(zip(columns, row))


__all__ = ["VersionedExtensionRegistryCore", "version_matches"]
