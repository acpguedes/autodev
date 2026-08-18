"""Durable, tenant-scoped secret-version store (E33-S1, ADR-014).

Ciphertext is write-only through this module's ``create``/``rotate``
operations and read-only through ``resolve_latest_active`` -- the one
method the injection path (E33-S2) calls. Every other read
(``get_metadata``/``list_metadata``) returns :class:`SecretMetadata`,
which never carries a value, matching the "no API returns a stored
value" functional criterion at the storage boundary itself, not just by
API-layer convention.

Mirrors :class:`backend.quotas.store.QuotaStore`'s SQLite connection and
``BEGIN IMMEDIATE`` transaction pattern.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.secret_store.contracts import (
    SecretBackendKind,
    SecretMetadata,
    SecretNotFoundError,
    SecretReference,
    SecretRevokedError,
    SecretStatus,
)

_DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"


def _now() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat()


def _resolve_db_path(database_url: str) -> Path:
    """Resolve a ``sqlite://`` URL to a filesystem path, matching the core stores."""
    url = (database_url or _DEFAULT_DATABASE_URL).strip()
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
    elif url.startswith("sqlite://"):
        raw = url.removeprefix("sqlite://")
    else:
        raise ValueError(f"SecretStore requires a sqlite:// DATABASE_URL. Got: {url!r}")
    return Path(raw).expanduser().resolve()


def _row_to_metadata(row: sqlite3.Row) -> SecretMetadata:
    return SecretMetadata(
        reference=SecretReference(
            tenant_id=row["tenant_id"], project=row["project"], name=row["name"]
        ),
        version=row["version"],
        status=SecretStatus(row["status"]),
        backend_kind=SecretBackendKind(row["backend_kind"]),
        created_at=row["created_at"],
        rotated_at=row["rotated_at"],
        revoked_at=row["revoked_at"],
    )


class SecretStore:
    """SQLite-backed durable store for scoped, versioned secret ciphertext."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Open (creating if needed) the SQLite-backed secrets table.

        Args:
            db_path: Explicit database file path; defaults to resolving
                ``DATABASE_URL``.
        """
        self._db_path = db_path or _resolve_db_path(os.environ.get("DATABASE_URL", ""))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._create_schema(conn)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS secrets (
                tenant_id TEXT NOT NULL,
                project TEXT NOT NULL,
                name TEXT NOT NULL,
                version INTEGER NOT NULL,
                ciphertext TEXT NOT NULL,
                status TEXT NOT NULL,
                backend_kind TEXT NOT NULL,
                created_at TEXT NOT NULL,
                rotated_at TEXT,
                revoked_at TEXT,
                PRIMARY KEY (tenant_id, project, name, version)
            );
            CREATE INDEX IF NOT EXISTS idx_secrets_latest
                ON secrets(tenant_id, project, name, version DESC);
            """
        )

    def _latest_row(
        self, conn: sqlite3.Connection, reference: SecretReference
    ) -> Optional[sqlite3.Row]:
        return conn.execute(
            "SELECT * FROM secrets WHERE tenant_id = ? AND project = ? AND name = ? "
            "ORDER BY version DESC LIMIT 1",
            (reference.tenant_id, reference.project, reference.name),
        ).fetchone()

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
            conn.execute("BEGIN IMMEDIATE")
            if self._latest_row(conn, reference) is not None:
                conn.rollback()
                raise ValueError(
                    f"secret {reference.as_key()!r} already exists -- use rotate() instead"
                )
            created_at = _now()
            conn.execute(
                "INSERT INTO secrets "
                "(tenant_id, project, name, version, ciphertext, status, backend_kind, "
                " created_at, rotated_at, revoked_at) "
                "VALUES (?, ?, ?, 1, ?, ?, ?, ?, NULL, NULL)",
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
    ) -> SecretMetadata:
        """Store a new version of an existing secret, superseding the previous one.

        Args:
            reference: Scoped reference to rotate.
            ciphertext: Already-encrypted new value to store.
            backend_kind: Backend that produced ``ciphertext``.

        Returns:
            The new version's metadata.

        Raises:
            SecretNotFoundError: If no version exists yet for ``reference``.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._latest_row(conn, reference)
            if current is None:
                conn.rollback()
                raise SecretNotFoundError(reference)
            now = _now()
            next_version = current["version"] + 1
            conn.execute(
                "UPDATE secrets SET status = ?, rotated_at = ? "
                "WHERE tenant_id = ? AND project = ? AND name = ? AND version = ?",
                (
                    SecretStatus.SUPERSEDED.value,
                    now,
                    reference.tenant_id,
                    reference.project,
                    reference.name,
                    current["version"],
                ),
            )
            conn.execute(
                "INSERT INTO secrets "
                "(tenant_id, project, name, version, ciphertext, status, backend_kind, "
                " created_at, rotated_at, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
                (
                    reference.tenant_id,
                    reference.project,
                    reference.name,
                    next_version,
                    ciphertext,
                    SecretStatus.ACTIVE.value,
                    backend_kind.value,
                    now,
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
            conn.execute("BEGIN IMMEDIATE")
            current = self._latest_row(conn, reference)
            if current is None:
                conn.rollback()
                raise SecretNotFoundError(reference)
            revoked_at = _now()
            conn.execute(
                "UPDATE secrets SET status = ?, revoked_at = ? "
                "WHERE tenant_id = ? AND project = ? AND name = ? AND version = ?",
                (
                    SecretStatus.REVOKED.value,
                    revoked_at,
                    reference.tenant_id,
                    reference.project,
                    reference.name,
                    current["version"],
                ),
            )
            conn.commit()
        metadata = self.get_metadata(reference)
        assert metadata is not None
        return metadata

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
        with self._connect() as conn:
            row = self._latest_row(conn, reference)
        if row is None:
            raise SecretNotFoundError(reference)
        metadata = _row_to_metadata(row)
        if metadata.status is SecretStatus.REVOKED:
            raise SecretRevokedError(reference, revoked_at=metadata.revoked_at or "")
        return row["ciphertext"], metadata

    def get_metadata(self, reference: SecretReference) -> Optional[SecretMetadata]:
        """Return a secret's latest version's metadata, or ``None`` if unknown."""
        with self._connect() as conn:
            row = self._latest_row(conn, reference)
        return _row_to_metadata(row) if row is not None else None

    def list_metadata(self, tenant_id: str, *, project: Optional[str] = None) -> list[SecretMetadata]:
        """List the latest-version metadata of every secret in a tenant (optionally scoped to one project).

        Args:
            tenant_id: Tenant to list secrets for.
            project: Optional project to further scope the listing.

        Returns:
            Latest-version metadata, one entry per distinct
            ``(project, name)``, in no particular order.
        """
        with self._connect() as conn:
            if project is not None:
                rows = conn.execute(
                    "SELECT s.* FROM secrets s "
                    "INNER JOIN ("
                    "  SELECT tenant_id, project, name, MAX(version) AS max_version "
                    "  FROM secrets WHERE tenant_id = ? AND project = ? "
                    "  GROUP BY tenant_id, project, name"
                    ") latest ON s.tenant_id = latest.tenant_id AND s.project = latest.project "
                    "  AND s.name = latest.name AND s.version = latest.max_version",
                    (tenant_id, project),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT s.* FROM secrets s "
                    "INNER JOIN ("
                    "  SELECT tenant_id, project, name, MAX(version) AS max_version "
                    "  FROM secrets WHERE tenant_id = ? "
                    "  GROUP BY tenant_id, project, name"
                    ") latest ON s.tenant_id = latest.tenant_id AND s.project = latest.project "
                    "  AND s.name = latest.name AND s.version = latest.max_version",
                    (tenant_id,),
                ).fetchall()
        return [_row_to_metadata(row) for row in rows]


__all__ = ["SecretStore"]
