"""Durable, tenant-scoped secret-version store (E33-S1, ADR-014; E52).

Runs on both SQLite and PostgreSQL through the shared persistence contract
(E49, ADR-025; E52), following the same port pattern
:class:`~backend.quotas.store.QuotaStore` established in E51. Every write
(create/rotate/revoke) for a given secret reference is serialized with a
transaction-scoped PostgreSQL advisory lock keyed by the reference (a no-op
on SQLite, where :func:`~backend.persistence.contract.begin_write`'s
``BEGIN IMMEDIATE`` already holds a whole-database write lock) -- this
closes the same "read latest, then conditionally insert a new row" race
E51-S2 identified for quota policies and leases: a plain ``SELECT ... FOR
UPDATE`` on the current row cannot protect a rotation, because once that
lock is granted, PostgreSQL re-reads the row's committed values, which
still show the *old* version number even though a concurrent transaction
already inserted a new one. The lock plus the "exactly one active version"
partial unique index (migration ``secrets_rotation_integrity``) close it
from two directions, so a bug in one is not the only thing standing between
a coherent version chain and a duplicate.

Ciphertext is write-only through this module's ``create``/``rotate``
operations and read-only through ``resolve_latest_active`` -- the one
method the injection path (E33-S2) calls. Every other read
(``get_metadata``/``list_metadata``) returns :class:`SecretMetadata`,
which never carries a value, matching the "no API returns a stored
value" functional criterion at the storage boundary itself, not just by
API-layer convention.

The ``secrets`` table carries Row-Level Security on PostgreSQL (E50-S4):
every tenant-scoped operation calls
:func:`~backend.persistence.tenancy.set_postgres_tenant` to set the
``app.tenant_id`` GUC inside the same transaction as its query, via
:meth:`SecretStore._scope` (a no-op on SQLite, which has no RLS and is
scoped by the ``WHERE tenant_id = ...`` clauses already present in each
query).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.persistence import contract
from backend.persistence.database import get_store
from backend.persistence.tenancy import set_postgres_tenant
from backend.secret_store.contracts import (
    SecretBackendKind,
    SecretMetadata,
    SecretNotFoundError,
    SecretReference,
    SecretRevokedError,
    SecretStatus,
)

_LATEST_ROW_COLUMNS = "version, status, backend_kind, ciphertext, created_at, rotated_at, revoked_at"


def _now() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat()


def _ts(value: Any) -> Optional[str]:
    """Normalize a timestamp column value to ISO-8601 text, or ``None``.

    SQLite stores ``created_at``/``rotated_at``/``revoked_at`` as the TEXT
    :func:`_now` wrote; PostgreSQL's ``TIMESTAMPTZ`` columns instead come
    back from psycopg as native :class:`datetime.datetime` objects, which
    :class:`~backend.secret_store.contracts.SecretMetadata` (``str | None``)
    cannot hold as-is -- the same normalization
    ``backend.persistence.postgres_adapter`` already applies to its own
    timestamp columns.

    Args:
        value: Raw column value (``str``, ``datetime``, or ``None``).

    Returns:
        ``None`` if ``value`` is ``None``; otherwise its string form.
    """
    return None if value is None else str(value)


class SecretStore:
    """Durable store for scoped, versioned secret ciphertext, on either backend."""

    def __init__(self, db_path: Optional[Path] = None, *, store: Any = None) -> None:
        """Open the store against an explicit SQLite file, an injected store, or the configured one.

        Args:
            db_path: When given (and ``store`` is not), a SQLite file to open
                directly -- built into a dedicated
                :class:`~backend.persistence.sqlite_adapter.store.SQLiteStore`
                so tests can exercise real, independently-connected SQLite
                instances against the same file.
            store: An existing store exposing ``connect()`` (a
                :class:`~backend.persistence.sqlite_adapter.store.SQLiteStore`
                or ``PostgresStore``). Takes precedence over ``db_path``.
                Defaults to the process-wide configured store
                (:func:`backend.persistence.database.get_store`) when neither
                is given -- the path production takes.

        Raises:
            TypeError: If the resolved store does not expose ``connect()``.
        """
        if store is None and db_path is not None:
            from backend.persistence.sqlite_adapter.store import SQLiteStore  # noqa: PLC0415

            store = SQLiteStore(f"sqlite:///{db_path}")
        self._store = store or get_store()
        if not hasattr(self._store, "connect"):
            raise TypeError("SecretStore requires a durable store with connect()")

    # --------------------------------------------------------------- helpers

    @property
    def _is_postgres(self) -> bool:
        """Whether the backing store is a PostgreSQL database."""
        return contract.is_postgres(getattr(self._store, "database_url", ""))

    def _sql(self, template: str) -> str:
        """Substitute this store's dialect placeholder into a SQL template."""
        return contract.sql(template, self._is_postgres)

    def _connect(self) -> Any:
        """Open a fresh connection from the backing store."""
        return self._store.connect()

    def _begin_write(self, conn: Any) -> None:
        """Start a write transaction eagerly on SQLite; a no-op on PostgreSQL."""
        contract.begin_write(conn, self._is_postgres)

    def _scope(self, conn: Any, tenant_id: str) -> None:
        """Set the PostgreSQL tenant GUC for this transaction; a no-op on SQLite."""
        if self._is_postgres:
            set_postgres_tenant(conn, tenant_id)

    def _lock_secret_for_write(self, conn: Any, reference: SecretReference) -> None:
        """Serialize every writer for one secret reference against each other, on PostgreSQL.

        create/rotate/revoke all read the current latest version and then
        conditionally write -- the same "phantom row" shape E51-S2
        identified for quota policies and leases, where ``SELECT ... FOR
        UPDATE`` alone cannot protect a rotation because the row it locks
        does not yet reflect a concurrently-inserted new version. A
        transaction-scoped advisory lock keyed by the reference (released
        automatically at commit or rollback) gives every writer for the
        same secret the whole-database serialization SQLite's
        ``BEGIN IMMEDIATE`` already provides for free.

        Args:
            conn: Open connection with an in-progress write transaction.
            reference: Secret reference whose writers should be serialized.
        """
        if self._is_postgres:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (reference.as_key(),))

    def _latest_row(self, conn: Any, reference: SecretReference) -> Optional[tuple]:
        return conn.execute(
            self._sql(
                f"SELECT {_LATEST_ROW_COLUMNS} FROM secrets "
                "WHERE tenant_id = {p} AND project = {p} AND name = {p} "
                "ORDER BY version DESC LIMIT 1"
            ),
            (reference.tenant_id, reference.project, reference.name),
        ).fetchone()

    @staticmethod
    def _row_to_metadata(reference: SecretReference, row: tuple) -> SecretMetadata:
        return SecretMetadata(
            reference=reference,
            version=row[0],
            status=SecretStatus(row[1]),
            backend_kind=SecretBackendKind(row[2]),
            created_at=_ts(row[4]) or "",
            rotated_at=_ts(row[5]),
            revoked_at=_ts(row[6]),
        )

    # ------------------------------------------------------------- writes

    def create(
        self,
        reference: SecretReference,
        ciphertext: str,
        *,
        backend_kind: SecretBackendKind = SecretBackendKind.ENCRYPTED_DATABASE,
    ) -> SecretMetadata:
        """Create the first version of a new secret.

        Args:
            reference: Scoped reference to create.
            ciphertext: Already-encrypted value to store.
            backend_kind: Backend that produced ``ciphertext``.

        Returns:
            The stored version's metadata.

        Raises:
            ValueError: If a version already exists for ``reference`` --
                callers must ``rotate`` an existing secret instead.
        """
        with self._connect() as conn:
            self._scope(conn, reference.tenant_id)
            self._begin_write(conn)
            self._lock_secret_for_write(conn, reference)
            if self._latest_row(conn, reference) is not None:
                conn.rollback()
                raise ValueError(
                    f"secret {reference.as_key()!r} already exists -- use rotate() instead"
                )
            created_at = _now()
            conn.execute(
                self._sql(
                    "INSERT INTO secrets "
                    "(tenant_id, project, name, version, ciphertext, status, backend_kind, "
                    " created_at, rotated_at, revoked_at) "
                    "VALUES ({p}, {p}, {p}, 1, {p}, {p}, {p}, {p}, NULL, NULL)"
                ),
                (
                    reference.tenant_id,
                    reference.project,
                    reference.name,
                    ciphertext,
                    SecretStatus.ACTIVE.value,
                    backend_kind.value,
                    created_at,
                ),
            )
            conn.commit()
        metadata = self.get_metadata(reference)
        assert metadata is not None
        return metadata

    def rotate(
        self,
        reference: SecretReference,
        ciphertext: str,
        *,
        backend_kind: SecretBackendKind = SecretBackendKind.ENCRYPTED_DATABASE,
        idempotency_key: Optional[str] = None,
    ) -> SecretMetadata:
        """Store a new version of an existing secret, superseding the previous one.

        Args:
            reference: Scoped reference to rotate.
            ciphertext: Already-encrypted new value to store.
            backend_kind: Backend that produced ``ciphertext``.
            idempotency_key: When given, a retry of this exact rotation
                request (same reference, same key) returns the version
                already created for it instead of creating another one.
                ``None`` (the default) performs a plain, non-idempotent
                rotation, matching prior behavior.

        Returns:
            The new version's metadata.

        Raises:
            SecretNotFoundError: If no version exists yet for ``reference``.
        """
        with self._connect() as conn:
            self._scope(conn, reference.tenant_id)
            self._begin_write(conn)
            self._lock_secret_for_write(conn, reference)
            if idempotency_key is not None:
                existing = conn.execute(
                    self._sql(
                        "SELECT version FROM secrets WHERE tenant_id = {p} AND project = {p} "
                        "AND name = {p} AND rotation_request_id = {p}"
                    ),
                    (reference.tenant_id, reference.project, reference.name, idempotency_key),
                ).fetchone()
                if existing is not None:
                    conn.commit()
                    metadata = self.get_metadata(reference)
                    assert metadata is not None
                    return metadata
            current = self._latest_row(conn, reference)
            if current is None:
                conn.rollback()
                raise SecretNotFoundError(reference)
            now = _now()
            next_version = current[0] + 1
            conn.execute(
                self._sql(
                    "UPDATE secrets SET status = {p}, rotated_at = {p} "
                    "WHERE tenant_id = {p} AND project = {p} AND name = {p} AND version = {p}"
                ),
                (
                    SecretStatus.SUPERSEDED.value,
                    now,
                    reference.tenant_id,
                    reference.project,
                    reference.name,
                    current[0],
                ),
            )
            conn.execute(
                self._sql(
                    "INSERT INTO secrets "
                    "(tenant_id, project, name, version, ciphertext, status, backend_kind, "
                    " created_at, rotated_at, revoked_at, rotation_request_id) "
                    "VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, NULL, NULL, {p})"
                ),
                (
                    reference.tenant_id,
                    reference.project,
                    reference.name,
                    next_version,
                    ciphertext,
                    SecretStatus.ACTIVE.value,
                    backend_kind.value,
                    now,
                    idempotency_key,
                ),
            )
            conn.commit()
        metadata = self.get_metadata(reference)
        assert metadata is not None
        return metadata

    def revoke(self, reference: SecretReference) -> SecretMetadata:
        """Revoke a secret's latest version, failing all future resolution closed.

        Args:
            reference: Scoped reference to revoke.

        Returns:
            The revoked version's metadata.

        Raises:
            SecretNotFoundError: If no version exists for ``reference``.
        """
        with self._connect() as conn:
            self._scope(conn, reference.tenant_id)
            self._begin_write(conn)
            self._lock_secret_for_write(conn, reference)
            current = self._latest_row(conn, reference)
            if current is None:
                conn.rollback()
                raise SecretNotFoundError(reference)
            revoked_at = _now()
            conn.execute(
                self._sql(
                    "UPDATE secrets SET status = {p}, revoked_at = {p} "
                    "WHERE tenant_id = {p} AND project = {p} AND name = {p} AND version = {p}"
                ),
                (
                    SecretStatus.REVOKED.value,
                    revoked_at,
                    reference.tenant_id,
                    reference.project,
                    reference.name,
                    current[0],
                ),
            )
            conn.commit()
        metadata = self.get_metadata(reference)
        assert metadata is not None
        return metadata

    # -------------------------------------------------------------- reads

    def resolve_latest_active(self, reference: SecretReference) -> tuple[str, SecretMetadata]:
        """Resolve a secret's latest version's ciphertext -- the sole read-value path.

        Only the injection path (E33-S2) should call this; every other
        caller gets metadata alone via :meth:`get_metadata`/:meth:`list_metadata`.

        Args:
            reference: Scoped reference to resolve.

        Returns:
            A ``(ciphertext, metadata)`` pair for the latest version.

        Raises:
            SecretNotFoundError: If no version exists for ``reference``.
            SecretRevokedError: If the latest version was revoked -- fails
                closed rather than falling back to an older active version.
        """
        conn = self._connect()
        self._scope(conn, reference.tenant_id)
        row = self._latest_row(conn, reference)
        if row is None:
            raise SecretNotFoundError(reference)
        metadata = self._row_to_metadata(reference, row)
        if metadata.status is SecretStatus.REVOKED:
            raise SecretRevokedError(reference, revoked_at=metadata.revoked_at or "")
        return row[3], metadata

    def get_metadata(self, reference: SecretReference) -> Optional[SecretMetadata]:
        """Return a secret's latest version's metadata, or ``None`` if unknown."""
        conn = self._connect()
        self._scope(conn, reference.tenant_id)
        row = self._latest_row(conn, reference)
        return self._row_to_metadata(reference, row) if row is not None else None

    def list_metadata(self, tenant_id: str, *, project: Optional[str] = None) -> list[SecretMetadata]:
        """List the latest-version metadata of every secret in a tenant (optionally scoped to one project).

        Args:
            tenant_id: Tenant to list secrets for.
            project: Optional project to further scope the listing.

        Returns:
            Latest-version metadata, one entry per distinct
            ``(project, name)``, in no particular order.
        """
        conn = self._connect()
        self._scope(conn, tenant_id)
        columns = "s.tenant_id, s.project, s.name, s.version, s.status, s.backend_kind, s.created_at, s.rotated_at, s.revoked_at"
        if project is not None:
            rows = conn.execute(
                self._sql(
                    f"SELECT {columns} FROM secrets s "
                    "INNER JOIN ("
                    "  SELECT tenant_id, project, name, MAX(version) AS max_version "
                    "  FROM secrets WHERE tenant_id = {p} AND project = {p} "
                    "  GROUP BY tenant_id, project, name"
                    ") latest ON s.tenant_id = latest.tenant_id AND s.project = latest.project "
                    "  AND s.name = latest.name AND s.version = latest.max_version"
                ),
                (tenant_id, project),
            ).fetchall()
        else:
            rows = conn.execute(
                self._sql(
                    f"SELECT {columns} FROM secrets s "
                    "INNER JOIN ("
                    "  SELECT tenant_id, project, name, MAX(version) AS max_version "
                    "  FROM secrets WHERE tenant_id = {p} "
                    "  GROUP BY tenant_id, project, name"
                    ") latest ON s.tenant_id = latest.tenant_id AND s.project = latest.project "
                    "  AND s.name = latest.name AND s.version = latest.max_version"
                ),
                (tenant_id,),
            ).fetchall()
        return [
            SecretMetadata(
                reference=SecretReference(tenant_id=row[0], project=row[1], name=row[2]),
                version=row[3],
                status=SecretStatus(row[4]),
                backend_kind=SecretBackendKind(row[5]),
                created_at=_ts(row[6]) or "",
                rotated_at=_ts(row[7]),
                revoked_at=_ts(row[8]),
            )
            for row in rows
        ]


__all__ = ["SecretStore"]
