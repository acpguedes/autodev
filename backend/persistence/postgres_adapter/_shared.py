"""Connection helpers and the connection-owner typing base shared across submodules."""

from __future__ import annotations

from typing import Any, Iterable

_DEFAULT_DATABASE_URL = "postgresql://autodev:autodev@postgres:5432/autodev"


def _connect(database_url: str) -> Any:
    """Open a new psycopg connection to the given PostgreSQL URL.

    Args:
        database_url: PostgreSQL connection URL.

    Returns:
        A new database connection.

    Raises:
        RuntimeError: If the ``psycopg`` package is not installed.
    """
    try:
        import psycopg  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised when optional dep missing
        raise RuntimeError(
            "psycopg is required for PostgreSQL persistence. Install backend requirements."
        ) from exc
    return psycopg.connect(database_url)


def _run_sql(conn: Any, statements: Iterable[str]) -> None:
    """Execute and commit a sequence of SQL statements on one connection."""
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()


class _ConnectionOwner:
    """Typing base for ``PostgresStore``'s mixins: declares the ``connect()`` every mixin calls.

    ``PostgresStore`` (in :mod:`store`) provides the real implementation;
    this placeholder exists only so each mixin can be read, and type-checked,
    on its own without depending on the composed class.
    """

    database_url: str

    def connect(self) -> Any:  # pragma: no cover - overridden by PostgresStore
        raise NotImplementedError


__all__ = ["_ConnectionOwner", "_DEFAULT_DATABASE_URL", "_connect", "_run_sql"]
