"""Durable persistence for service credentials and browser sessions.

Follows the same store/dialect conventions as
:class:`backend.events.store.EventStore`: a shared durable store
(:func:`backend.persistence.database.get_store`), ``{p}`` placeholder
substitution, and one lazily-opened connection per thread.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from backend.auth.contracts import AccessAuditRecord, AuthMethod, AuthSessionRecord, Role, ServiceCredentialRecord
from backend.auth.migrations import auth_store_statements
from backend.auth.roles import normalize_scopes
from backend.persistence import contract
from backend.persistence.database import get_store


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``."""
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    """Serialize a ``datetime`` to a sortable ISO-8601 string."""
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str | datetime) -> datetime:
    """Parse a row's timestamp value into a timezone-aware ``datetime``.

    SQLite's ``TEXT`` timestamp columns come back as ``str``, but psycopg
    deserializes PostgreSQL's ``TIMESTAMPTZ`` columns
    (``auth_store_statements``) directly into ``datetime`` objects -- accept
    either rather than assuming the SQLite shape (E57).
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _encode_roles(roles: tuple[Role, ...]) -> str:
    """Serialize a role tuple to a stable, storable string."""
    return ",".join(role.value for role in roles)


def _decode_roles(value: str) -> tuple[Role, ...]:
    """Parse a stored role string back into a role tuple."""
    return tuple(Role(item) for item in value.split(",") if item)


def _encode_scopes(scopes: frozenset[str]) -> str:
    """Serialize a scope set to a stable, storable string."""
    return " ".join(sorted(scopes))


class AuthStore:
    """Durable service-credential and session persistence (E11-S2)."""

    def __init__(self, store: Any | None = None) -> None:
        """Initialize the store, ensuring its backing schema exists.

        Args:
            store: Durable store to use; defaults to the process-wide store
                from :func:`backend.persistence.database.get_store`.

        Raises:
            TypeError: If ``store`` does not expose a ``connect()`` method.
        """
        self._store = store or get_store()
        if not hasattr(self._store, "connect"):
            raise TypeError("AuthStore requires a durable store with connect()")
        self._local = threading.local()
        self._ensure_schema()

    # ------------------------------------------------------- service keys

    def create_service_credential(self, record: ServiceCredentialRecord) -> None:
        """Persist a newly minted service credential.

        Args:
            record: The credential to persist. Its ``secret_hash`` is the
                only representation of the secret ever stored.
        """
        conn = self._connect()
        try:
            self._begin_write(conn)
            conn.execute(
                self._sql(
                    "INSERT INTO service_credentials "
                    "(key_id, tenant_id, subject, secret_hash, roles, scopes, "
                    "created_at, expires_at, revoked_at) "
                    "VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})"
                ),
                (
                    record.key_id,
                    record.tenant_id,
                    record.subject,
                    record.secret_hash,
                    _encode_roles(record.roles),
                    _encode_scopes(record.scopes),
                    _iso(record.created_at),
                    _iso(record.expires_at),
                    _iso(record.revoked_at) if record.revoked_at else None,
                ),
            )
            conn.commit()
        except Exception:
            self._drop_connection()
            raise

    def get_service_credential(self, key_id: str) -> ServiceCredentialRecord | None:
        """Fetch one service credential by its non-secret id.

        Args:
            key_id: The credential's non-secret identifier.

        Returns:
            The credential, or ``None`` if unknown.
        """
        row = self._connect().execute(
            self._sql(
                "SELECT key_id, tenant_id, subject, secret_hash, roles, scopes, "
                "created_at, expires_at, revoked_at FROM service_credentials "
                "WHERE key_id = {p}"
            ),
            (key_id,),
        ).fetchone()
        return self._decode_credential(row) if row is not None else None

    def list_service_credentials(self, *, tenant_id: str) -> list[ServiceCredentialRecord]:
        """List every service credential belonging to one tenant.

        Args:
            tenant_id: Tenant to scope the listing to.

        Returns:
            The tenant's credentials, most recently created first.
        """
        rows = self._connect().execute(
            self._sql(
                "SELECT key_id, tenant_id, subject, secret_hash, roles, scopes, "
                "created_at, expires_at, revoked_at FROM service_credentials "
                "WHERE tenant_id = {p} ORDER BY created_at DESC"
            ),
            (tenant_id,),
        ).fetchall()
        return [self._decode_credential(row) for row in rows]

    def revoke_service_credential(self, *, tenant_id: str, key_id: str) -> bool:
        """Immediately revoke one active service credential.

        Args:
            tenant_id: Tenant that must own the credential.
            key_id: The credential's non-secret identifier.

        Returns:
            ``True`` if an active credential was revoked; ``False`` if it did
            not exist, belonged to another tenant, or was already revoked.
        """
        conn = self._connect()
        try:
            self._begin_write(conn)
            cursor = conn.execute(
                self._sql(
                    "UPDATE service_credentials SET revoked_at = {p} "
                    "WHERE key_id = {p} AND tenant_id = {p} AND revoked_at IS NULL"
                ),
                (_iso(utcnow()), key_id, tenant_id),
            )
            conn.commit()
            return (cursor.rowcount or 0) > 0
        except Exception:
            self._drop_connection()
            raise

    def has_active_service_credential(self) -> bool:
        """Return whether any tenant has at least one active service credential.

        Used only by :func:`backend.auth.readiness.validate_auth_readiness`
        as one of production's two acceptable bootstrap paths.

        Returns:
            ``True`` if at least one unrevoked, unexpired credential exists.
        """
        row = self._connect().execute(
            self._sql(
                "SELECT 1 FROM service_credentials "
                "WHERE revoked_at IS NULL AND expires_at > {p} LIMIT 1"
            ),
            (_iso(utcnow()),),
        ).fetchone()
        return row is not None

    def _decode_credential(self, row: Any) -> ServiceCredentialRecord:
        """Decode one ``service_credentials`` row into its typed record."""
        values = list(row)
        return ServiceCredentialRecord(
            key_id=values[0],
            tenant_id=values[1],
            subject=values[2],
            secret_hash=values[3],
            roles=_decode_roles(values[4]),
            scopes=normalize_scopes(values[5]) if values[5] else frozenset(),
            created_at=_parse_iso(values[6]),
            expires_at=_parse_iso(values[7]),
            revoked_at=_parse_iso(values[8]) if values[8] else None,
        )

    # ---------------------------------------------------------- sessions

    def create_session(self, record: AuthSessionRecord) -> None:
        """Persist a newly created browser session.

        Args:
            record: The session to persist, with its refresh token already
                Fernet-encrypted.
        """
        conn = self._connect()
        try:
            self._begin_write(conn)
            conn.execute(
                self._sql(
                    "INSERT INTO auth_sessions "
                    "(session_id, tenant_id, subject, roles, "
                    "encrypted_refresh_token, created_at, expires_at, revoked_at) "
                    "VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})"
                ),
                (
                    record.session_id,
                    record.tenant_id,
                    record.subject,
                    _encode_roles(record.roles),
                    record.encrypted_refresh_token,
                    _iso(record.created_at),
                    _iso(record.expires_at),
                    _iso(record.revoked_at) if record.revoked_at else None,
                ),
            )
            conn.commit()
        except Exception:
            self._drop_connection()
            raise

    def get_session(self, session_id: str) -> AuthSessionRecord | None:
        """Fetch one browser session by its opaque id.

        Args:
            session_id: The session cookie's value.

        Returns:
            The session, or ``None`` if unknown.
        """
        row = self._connect().execute(
            self._sql(
                "SELECT session_id, tenant_id, subject, roles, "
                "encrypted_refresh_token, created_at, expires_at, revoked_at "
                "FROM auth_sessions WHERE session_id = {p}"
            ),
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        values = list(row)
        return AuthSessionRecord(
            session_id=values[0],
            tenant_id=values[1],
            subject=values[2],
            roles=_decode_roles(values[3]),
            encrypted_refresh_token=values[4],
            created_at=_parse_iso(values[5]),
            expires_at=_parse_iso(values[6]),
            revoked_at=_parse_iso(values[7]) if values[7] else None,
        )

    def revoke_session(self, session_id: str) -> bool:
        """Revoke one browser session (logout).

        Args:
            session_id: The session cookie's value.

        Returns:
            ``True`` if an active session was revoked.
        """
        conn = self._connect()
        try:
            self._begin_write(conn)
            cursor = conn.execute(
                self._sql(
                    "UPDATE auth_sessions SET revoked_at = {p} "
                    "WHERE session_id = {p} AND revoked_at IS NULL"
                ),
                (_iso(utcnow()), session_id),
            )
            conn.commit()
            return (cursor.rowcount or 0) > 0
        except Exception:
            self._drop_connection()
            raise

    # ------------------------------------------------------- access audit

    def append_access_audit(self, record: AccessAuditRecord) -> None:
        """Durably append one access-decision audit row.

        Args:
            record: The audit row to persist.

        Raises:
            Exception: Any persistence failure (connection, disk, etc.) is
                re-raised uncaught — the caller (Task 4's enforcement
                wiring) treats an audit-write failure for an otherwise
                allowed request as a hard denial (``503``), so silently
                swallowing it here would defeat that guarantee.
        """
        conn = self._connect()
        try:
            self._begin_write(conn)
            conn.execute(
                self._sql(
                    "INSERT INTO access_audit "
                    "(audit_id, occurred_at, tenant_id, subject, auth_method, "
                    "credential_id, roles, required_scope, resource_type, "
                    "resource_id, method, route_template, decision, reason, "
                    "request_id) "
                    "VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, "
                    "{p}, {p}, {p}, {p}, {p})"
                ),
                (
                    record.audit_id,
                    _iso(record.occurred_at),
                    record.tenant_id,
                    record.subject,
                    record.auth_method.value,
                    record.credential_id,
                    _encode_roles(record.roles),
                    record.required_scope,
                    record.resource_type,
                    record.resource_id,
                    record.method,
                    record.route_template,
                    record.decision,
                    record.reason,
                    record.request_id,
                ),
            )
            conn.commit()
        except Exception:
            self._drop_connection()
            raise

    def list_access_audit(
        self, *, tenant_id: str, limit: int, before: datetime | None
    ) -> list[AccessAuditRecord]:
        """List a tenant's access-audit rows, most recent first.

        Args:
            tenant_id: Tenant to scope the listing to.
            limit: Maximum rows to return.
            before: If given, only rows strictly older than this timestamp.

        Returns:
            The tenant's audit rows, most recently occurred first.
        """
        if before is not None:
            rows = self._connect().execute(
                self._sql(
                    "SELECT audit_id, occurred_at, tenant_id, subject, auth_method, "
                    "credential_id, roles, required_scope, resource_type, "
                    "resource_id, method, route_template, decision, reason, "
                    "request_id FROM access_audit "
                    "WHERE tenant_id = {p} AND occurred_at < {p} "
                    "ORDER BY occurred_at DESC LIMIT {p}"
                ),
                (tenant_id, _iso(before), limit),
            ).fetchall()
        else:
            rows = self._connect().execute(
                self._sql(
                    "SELECT audit_id, occurred_at, tenant_id, subject, auth_method, "
                    "credential_id, roles, required_scope, resource_type, "
                    "resource_id, method, route_template, decision, reason, "
                    "request_id FROM access_audit "
                    "WHERE tenant_id = {p} "
                    "ORDER BY occurred_at DESC LIMIT {p}"
                ),
                (tenant_id, limit),
            ).fetchall()
        return [self._decode_audit(row) for row in rows]

    def _decode_audit(self, row: Any) -> AccessAuditRecord:
        """Decode one ``access_audit`` row into its typed record."""
        values = list(row)
        return AccessAuditRecord(
            audit_id=values[0],
            occurred_at=_parse_iso(values[1]),
            tenant_id=values[2],
            subject=values[3],
            auth_method=AuthMethod(values[4]),
            credential_id=values[5],
            roles=_decode_roles(values[6]),
            required_scope=values[7],
            resource_type=values[8],
            resource_id=values[9],
            method=values[10],
            route_template=values[11],
            decision=values[12],
            reason=values[13],
            request_id=values[14],
        )

    # ----------------------------------------------------------- helpers

    @property
    def _is_postgres(self) -> bool:
        """Whether the backing store is a PostgreSQL database."""
        return contract.is_postgres(getattr(self._store, "database_url", ""))

    def _sql(self, template: str) -> str:
        """Substitute the dialect placeholder into a SQL template."""
        return contract.sql(template, self._is_postgres)

    def _connect(self) -> Any:
        """Return this thread's cached store connection, creating it once."""
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

    def _begin_write(self, conn: Any) -> None:
        """Start a write transaction eagerly on SQLite."""
        contract.begin_write(conn, self._is_postgres)

    def _ensure_schema(self) -> None:
        """Create the Auth Store tables if they do not exist."""
        conn = self._connect()
        for statement in auth_store_statements(self._is_postgres):
            conn.execute(statement)
        conn.commit()


__all__ = ["AuthStore", "utcnow"]
