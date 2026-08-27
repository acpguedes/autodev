"""Raw, non-mutating connection helpers for the E58 migrator.

Deliberately does not construct :class:`~backend.persistence.sqlite_adapter.SQLiteStore`
or :class:`~backend.persistence.postgres_adapter.PostgresStore` for the
*source* database: both stores run their versioned migrations on
construction, which would silently mutate a source whose schema is behind —
violating ADR-026 decision 2 ("the source database is never mutated"). A raw
``sqlite3``/``psycopg`` connection is used for every source read instead.
Destination access does construct the real store classes, deliberately: that
is how the destination schema gets created (ADR-026 decision 5).
"""

from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from backend.persistence.sqlite_adapter import _resolve_db_path


def open_source_connection(sqlite_url: str) -> sqlite3.Connection:
    """Open a read path to a source SQLite database without applying migrations.

    Args:
        sqlite_url: A ``sqlite://`` / ``sqlite:///`` URL.

    Returns:
        A raw ``sqlite3.Connection`` with row access by index (no
        ``row_factory`` override, matching :func:`PRAGMA table_info` /
        ``SELECT *`` positional order used throughout this package) and
        ``isolation_level=None`` (autocommit), so callers that need a
        consistent snapshot across many reads (:mod:`backend.persistence.sqlite_to_postgres.copy`)
        can issue an explicit ``BEGIN``/``ROLLBACK`` without Python's
        ``sqlite3`` module's implicit transaction handling interfering.

    Raises:
        FileNotFoundError: If the resolved database file does not exist.
    """
    path = _resolve_db_path(sqlite_url)
    if not path.exists():
        raise FileNotFoundError(f"source SQLite database not found: {path}")
    conn = sqlite3.connect(path)
    conn.isolation_level = None
    return conn


def open_dest_connection(postgres_url: str) -> Any:
    """Open a raw connection to a destination PostgreSQL database.

    Does not create or check any schema — callers that need the destination
    schema materialized should construct
    :class:`~backend.persistence.postgres_adapter.PostgresStore` (see this
    module's docstring).

    Args:
        postgres_url: A ``postgresql://`` / ``postgres://`` URL.

    Returns:
        A new psycopg connection.

    Raises:
        RuntimeError: If ``psycopg`` is not installed.
    """
    try:
        import psycopg  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised when optional dep missing
        raise RuntimeError(
            "psycopg is required for PostgreSQL persistence. Install backend requirements."
        ) from exc
    return psycopg.connect(postgres_url)


def redact_url(database_url: str) -> str:
    """Return *database_url* with any embedded password stripped, for safe logging.

    Connection strings must never appear in migrator output — the dry-run
    plan, the preflight report, or the persisted reconciliation report
    (ADR-026: "Connection strings for both databases must not be logged or
    written into the reconciliation report").

    Args:
        database_url: A ``sqlite://`` or ``postgresql://`` URL, possibly with
            an embedded password.

    Returns:
        The same URL with any password segment replaced by ``***``, or the
        original string unchanged if it carries no credentials to redact.
    """
    parsed = urlsplit(database_url)
    if parsed.password is None:
        return database_url
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    username = parsed.username or ""
    netloc = f"{username}:***@{host}{port}" if username else f"***@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


__all__ = ["open_dest_connection", "open_source_connection", "redact_url"]
