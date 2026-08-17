"""SQLite/PostgreSQL schema for the durable Auth Store (E11-S2).

Follows the dialect-parameterized DDL convention of
:func:`backend.events.records.event_store_statements`: SQLite gets ``TEXT``
timestamps, PostgreSQL gets ``TIMESTAMPTZ``.
"""

from __future__ import annotations


def auth_store_statements(is_postgres: bool) -> tuple[str, ...]:
    """Build the CREATE TABLE/INDEX statements for the Auth Store schema.

    Args:
        is_postgres: Whether to emit PostgreSQL types.

    Returns:
        The ordered DDL statements for ``service_credentials``,
        ``auth_sessions``, and ``access_audit``.
    """
    time_type = "TIMESTAMPTZ" if is_postgres else "TEXT"
    return (
        f"""
        CREATE TABLE IF NOT EXISTS service_credentials (
            key_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            secret_hash TEXT NOT NULL,
            roles TEXT NOT NULL,
            scopes TEXT NOT NULL,
            created_at {time_type} NOT NULL,
            expires_at {time_type} NOT NULL,
            revoked_at {time_type}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_service_credentials_tenant "
        "ON service_credentials (tenant_id)",
        f"""
        CREATE TABLE IF NOT EXISTS auth_sessions (
            session_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            roles TEXT NOT NULL,
            encrypted_refresh_token TEXT NOT NULL,
            created_at {time_type} NOT NULL,
            expires_at {time_type} NOT NULL,
            revoked_at {time_type}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_auth_sessions_tenant "
        "ON auth_sessions (tenant_id)",
        f"""
        CREATE TABLE IF NOT EXISTS access_audit (
            audit_id TEXT PRIMARY KEY,
            occurred_at {time_type} NOT NULL,
            tenant_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            auth_method TEXT NOT NULL,
            credential_id TEXT,
            roles TEXT NOT NULL,
            required_scope TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            method TEXT NOT NULL,
            route_template TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            request_id TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_access_audit_tenant_time "
        "ON access_audit (tenant_id, occurred_at)",
    )


__all__ = ["auth_store_statements"]
