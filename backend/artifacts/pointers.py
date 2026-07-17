"""Durable State Store registry of artifact pointers (E8-S3/T2).

The object stores in :mod:`backend.artifacts.store` persist payload bytes and
return an :class:`~backend.artifacts.store.ArtifactPointer`, but until this
module nothing recorded those pointers durably — meaning the platform could
not answer "which objects are still referenced?" and lifecycle cleanup
(:mod:`backend.artifacts.cleanup`) had to fall back to an age heuristic.

:class:`ArtifactPointerStore` follows the :class:`backend.events.store.EventStore`
precedent: it wraps the store returned by
:func:`backend.persistence.database.get_store`, creates its schema idempotently
on construction, and speaks both SQLite and PostgreSQL through a tiny dialect
shim — no changes to the persistence adapters themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import threading
from typing import Any
import uuid

from backend.artifacts.store import (
    ArtifactKind,
    ArtifactPointer,
    ArtifactStore,
)
from backend.events.records import utcnow_iso
from backend.persistence.database import get_store
from backend.persistence.tenancy import DEFAULT_TENANT_ID


def artifact_pointer_statements(is_postgres: bool) -> tuple[str, ...]:
    """Build the CREATE TABLE/INDEX statements for the artifact-pointer schema.

    Args:
        is_postgres: Whether to emit PostgreSQL types (JSONB/TIMESTAMPTZ).

    Returns:
        The ordered DDL statements.
    """
    if is_postgres:
        json_type, time_type = "JSONB", "TIMESTAMPTZ"
    else:
        json_type, time_type = "TEXT", "TEXT"
    return (
        f"""
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            kind TEXT NOT NULL,
            bucket TEXT NOT NULL,
            object_key TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            created_at {time_type} NOT NULL,
            context {json_type},
            UNIQUE (bucket, object_key)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_artifacts_tenant ON artifacts(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_artifacts_kind ON artifacts(tenant_id, kind)",
    )


@dataclass(frozen=True)
class StoredArtifact:
    """One durably recorded artifact pointer.

    Attributes:
        id: Server-assigned unique identifier of the record.
        tenant_id: Tenant the artifact belongs to.
        kind: Artifact category (:class:`~backend.artifacts.store.ArtifactKind` value).
        bucket: Bucket the payload was stored in.
        object_key: Relative object key within the bucket.
        sha256: SHA-256 digest of the stored payload.
        size_bytes: Size of the stored payload, in bytes.
        content_type: MIME type recorded for the payload.
        created_at: ISO-8601 UTC instant the pointer was recorded.
        context: Free-form JSON metadata linking the artifact to its
            producer (run id, patch id, export id, ...).
    """

    id: str
    tenant_id: str
    kind: str
    bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    content_type: str
    created_at: str
    context: dict[str, Any]

    @property
    def pointer(self) -> ArtifactPointer:
        """The object-store pointer equivalent of this record."""
        return ArtifactPointer(
            bucket=self.bucket,
            object_key=self.object_key,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            content_type=self.content_type,
        )


class ArtifactPointerStore:
    """Durable registry mapping stored artifact objects to State Store rows."""

    def __init__(self, store: Any | None = None) -> None:
        """Wrap a persistence store and ensure the artifact schema exists.

        Args:
            store: Persistence store to use; defaults to the configured store
                from :func:`backend.persistence.database.get_store`.
        """
        self._store = store or get_store()
        self._local = threading.local()
        self._ensure_schema()

    @property
    def backing_store(self) -> Any:
        """The wrapped persistence store."""
        return self._store

    def record(
        self,
        pointer: ArtifactPointer,
        *,
        kind: ArtifactKind | str,
        tenant_id: str = DEFAULT_TENANT_ID,
        context: dict[str, Any] | None = None,
    ) -> StoredArtifact:
        """Durably record a pointer returned by an artifact store write.

        Re-recording the same ``(bucket, object_key)`` updates the existing
        row in place (upsert), so retried writes stay idempotent.

        Args:
            pointer: Pointer returned by ``put_artifact``.
            kind: Artifact category the payload was stored under.
            tenant_id: Tenant the artifact belongs to.
            context: Free-form JSON metadata linking the artifact to its
                producer. Defaults to empty.

        Returns:
            The recorded :class:`StoredArtifact`.
        """
        record_id = str(uuid.uuid4())
        created_at = utcnow_iso()
        context_json = json.dumps(context or {})
        conn = self._connect()
        try:
            conn.execute(
                self._sql(
                    """
                    INSERT INTO artifacts (
                        id, tenant_id, kind, bucket, object_key, sha256,
                        size_bytes, content_type, created_at, context
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    ON CONFLICT (bucket, object_key) DO UPDATE SET
                        tenant_id = excluded.tenant_id,
                        kind = excluded.kind,
                        sha256 = excluded.sha256,
                        size_bytes = excluded.size_bytes,
                        content_type = excluded.content_type,
                        created_at = excluded.created_at,
                        context = excluded.context
                    """
                ),
                (
                    record_id,
                    tenant_id,
                    str(kind),
                    pointer.bucket,
                    pointer.object_key,
                    pointer.sha256,
                    pointer.size_bytes,
                    pointer.content_type,
                    created_at,
                    context_json,
                ),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            finally:
                self._drop_connection()
            raise
        stored = self.find_by_key(pointer.bucket, pointer.object_key, tenant_id=tenant_id)
        if stored is None:  # pragma: no cover - defensive; row was just written
            raise RuntimeError("artifact row vanished after insert")
        return stored

    def get(self, artifact_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> StoredArtifact | None:
        """Return one artifact record by id, scoped to a tenant.

        Args:
            artifact_id: Identifier assigned by :meth:`record`.
            tenant_id: Tenant the caller is scoped to.

        Returns:
            The matching record, or ``None`` when absent or owned by
            another tenant.
        """
        row = self._connect().execute(
            self._sql(
                "SELECT id, tenant_id, kind, bucket, object_key, sha256, size_bytes, "
                "content_type, created_at, context FROM artifacts "
                "WHERE id = {p} AND tenant_id = {p}"
            ),
            (artifact_id, tenant_id),
        ).fetchone()
        return self._decode(row) if row is not None else None

    def find_by_key(
        self,
        bucket: str,
        object_key: str,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> StoredArtifact | None:
        """Return the record for one stored object, scoped to a tenant.

        Args:
            bucket: Bucket the object lives in.
            object_key: Relative object key within the bucket.
            tenant_id: Tenant the caller is scoped to.

        Returns:
            The matching record, or ``None`` when absent or owned by
            another tenant.
        """
        row = self._connect().execute(
            self._sql(
                "SELECT id, tenant_id, kind, bucket, object_key, sha256, size_bytes, "
                "content_type, created_at, context FROM artifacts "
                "WHERE bucket = {p} AND object_key = {p} AND tenant_id = {p}"
            ),
            (bucket, object_key, tenant_id),
        ).fetchone()
        return self._decode(row) if row is not None else None

    def list(
        self,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        kind: ArtifactKind | str | None = None,
        limit: int = 100,
    ) -> list[StoredArtifact]:
        """List artifact records for a tenant, newest first.

        Args:
            tenant_id: Tenant the caller is scoped to.
            kind: Optional artifact-kind filter.
            limit: Maximum number of records to return.

        Returns:
            Matching records ordered by ``created_at`` descending.
        """
        sql = (
            "SELECT id, tenant_id, kind, bucket, object_key, sha256, size_bytes, "
            "content_type, created_at, context FROM artifacts WHERE tenant_id = {p}"
        )
        params: list[Any] = [tenant_id]
        if kind is not None:
            sql += " AND kind = {p}"
            params.append(str(kind))
        sql += " ORDER BY created_at DESC LIMIT {p}"
        params.append(int(limit))
        rows = self._connect().execute(self._sql(sql), tuple(params)).fetchall()
        return [self._decode(row) for row in rows]

    def delete(self, artifact_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> bool:
        """Delete one artifact record, scoped to a tenant.

        Only the pointer row is removed; deleting the stored payload is the
        cleanup module's job.

        Args:
            artifact_id: Identifier assigned by :meth:`record`.
            tenant_id: Tenant the caller is scoped to.

        Returns:
            ``True`` when a row was deleted, ``False`` otherwise.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                self._sql("DELETE FROM artifacts WHERE id = {p} AND tenant_id = {p}"),
                (artifact_id, tenant_id),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            finally:
                self._drop_connection()
            raise
        return bool(cursor.rowcount)

    def referenced_object_keys(self, *, bucket: str | None = None) -> set[str]:
        """Return every object key still referenced by a pointer row.

        This is the authoritative input for reference-based lifecycle
        cleanup (E8-S3/T4): any stored object whose key is absent from this
        set belongs to no recorded artifact and is safe to garbage-collect.
        Deliberately tenant-agnostic — cleanup must never delete another
        tenant's referenced objects.

        Args:
            bucket: Optional bucket filter.

        Returns:
            The set of referenced object keys.
        """
        sql = "SELECT object_key FROM artifacts"
        params: tuple[Any, ...] = ()
        if bucket is not None:
            sql += " WHERE bucket = {p}"
            params = (bucket,)
        rows = self._connect().execute(self._sql(sql), params).fetchall()
        return {str(row[0] if not hasattr(row, "keys") else list(row)[0]) for row in rows}

    def _decode(self, row: Any) -> StoredArtifact:
        """Decode a database row into a :class:`StoredArtifact`.

        Args:
            row: Row in SELECT column order.

        Returns:
            The decoded record.
        """
        values = list(row)
        raw_context = values[9]
        if isinstance(raw_context, (bytes, bytearray)):
            raw_context = raw_context.decode()
        context = raw_context if isinstance(raw_context, dict) else json.loads(raw_context or "{}")
        return StoredArtifact(
            id=str(values[0]),
            tenant_id=str(values[1]),
            kind=str(values[2]),
            bucket=str(values[3]),
            object_key=str(values[4]),
            sha256=str(values[5]),
            size_bytes=int(values[6]),
            content_type=str(values[7]),
            created_at=str(values[8]),
            context=context,
        )

    @property
    def _is_postgres(self) -> bool:
        """Whether the backing store is a PostgreSQL database."""
        url = str(getattr(self._store, "database_url", ""))
        return url.startswith(("postgresql://", "postgres://"))

    def _sql(self, template: str) -> str:
        """Substitute the dialect placeholder into a SQL template.

        Args:
            template: SQL text using ``{p}`` for parameter placeholders.

        Returns:
            The SQL with dialect-appropriate placeholders.
        """
        return template.format(p="%s" if self._is_postgres else "?")

    def _connect(self) -> Any:
        """Return this thread's cached store connection, creating it once.

        Mirrors :class:`backend.events.store.EventStore`: SQLite connections
        are not shareable across threads, so the cache is per-thread.

        Returns:
            A DB-API connection from the underlying store.
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._store.connect()
            if not self._is_postgres:
                conn.execute("PRAGMA busy_timeout=15000")
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def _drop_connection(self) -> None:
        """Discard this thread's cached connection after a failure."""
        conn = getattr(self._local, "conn", None)
        self._local.conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - already discarding
                pass

    def _ensure_schema(self) -> None:
        """Create the artifact-pointer table if it does not exist."""
        conn = self._connect()
        for statement in artifact_pointer_statements(self._is_postgres):
            conn.execute(statement)
        conn.commit()


def persist_artifact(
    store: ArtifactStore,
    pointers: ArtifactPointerStore,
    *,
    kind: ArtifactKind,
    object_key: str,
    payload: bytes,
    content_type: str = "application/octet-stream",
    tenant_id: str = DEFAULT_TENANT_ID,
    context: dict[str, Any] | None = None,
) -> StoredArtifact:
    """Store payload bytes and durably record the resulting pointer.

    Convenience helper combining ``put_artifact`` with
    :meth:`ArtifactPointerStore.record`, so callers cannot forget to
    register the reference.

    Args:
        store: Artifact object store to write the payload to.
        pointers: Pointer registry to record the reference in.
        kind: Category of artifact, determining its target bucket.
        object_key: Relative POSIX path identifying the object within the
            bucket; must be scoped to ``tenant_id`` per store conventions.
        payload: Raw bytes to store.
        content_type: MIME type to record for the stored object.
        tenant_id: Tenant the artifact belongs to.
        context: Free-form JSON metadata linking the artifact to its producer.

    Returns:
        The recorded :class:`StoredArtifact`.
    """
    pointer = store.put_artifact(kind, object_key, payload, content_type=content_type)
    return pointers.record(pointer, kind=kind, tenant_id=tenant_id, context=context)


__all__ = [
    "ArtifactPointerStore",
    "StoredArtifact",
    "artifact_pointer_statements",
    "persist_artifact",
]
