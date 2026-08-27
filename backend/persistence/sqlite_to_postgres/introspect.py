"""Generic, schema-introspection-driven column helpers for the E58 migrator.

Rather than hand-listing every column of every table (38 tables across the
full inventory, see :mod:`backend.persistence.sqlite_to_postgres.tables`),
the migrator asks each database directly: SQLite's ``PRAGMA table_info`` for
the source's column order, and PostgreSQL's ``information_schema.columns``
for the destination's column types and defaults. This keeps the table-copy
logic in :mod:`backend.persistence.sqlite_to_postgres.copy` at a fixed size
regardless of how many tables or columns the schema grows to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.persistence.sqlite_to_postgres.tables import TABLE_COPY_ORDER
from backend.persistence.tenancy import DEFAULT_TENANT_ID


@dataclass(frozen=True)
class SourceColumn:
    """One column of a source (SQLite) table, in declaration order.

    Attributes:
        name: Column name.
    """

    name: str


@dataclass(frozen=True)
class DestColumn:
    """One column of a destination (PostgreSQL) table.

    Attributes:
        name: Column name.
        is_jsonb: Whether the column's data type is ``jsonb`` — a bound
            string parameter needs an explicit ``::jsonb`` cast
            (:func:`backend.persistence.contract.jsonb_cast`).
        is_boolean: Whether the column's data type is ``boolean`` — SQLite
            stores booleans as ``0``/``1`` integers, which psycopg binds as
            integers; PostgreSQL rejects an integer into a ``boolean``
            column, so the value needs an explicit ``bool()`` coercion.
        is_serial: Whether the column is backed by a sequence
            (``column_default`` starts with ``nextval(``) — such a column's
            sequence must be advanced past the migrated maximum after the
            copy (E58-S2-T2).
        is_timestamp: Whether the column's data type is
            ``timestamp with[out] time zone`` — reconciliation
            (:mod:`backend.persistence.sqlite_to_postgres.reconcile`) parses
            such a column's value on both sides into a timezone-aware
            ``datetime`` before hashing, since SQLite stores it as text (in
            one of two formats depending on whether it was set by
            ``CURRENT_TIMESTAMP`` or application code) and PostgreSQL
            returns a ``datetime.datetime`` object.
    """

    name: str
    is_jsonb: bool
    is_boolean: bool
    is_serial: bool
    is_timestamp: bool = False


def source_table_names(conn: Any) -> list[str]:
    """List every user table in a SQLite database, source order.

    Args:
        conn: Open ``sqlite3.Connection``.

    Returns:
        Table names from ``sqlite_master``, excluding SQLite-internal
        tables (``sqlite_%``) — the caller is responsible for filtering
        out this migrator's own known-ignored tables (``schema_version``).
    """
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
    ).fetchall()
    return [row[0] for row in rows]


def source_table_exists(conn: Any, table: str) -> bool:
    """Whether *table* exists in the connected SQLite database.

    A table this migrator knows about (:data:`~backend.persistence.sqlite_to_postgres.tables.TABLE_COPY_ORDER`)
    may still be absent from a given source: its owning subsystem (e.g. the
    flow engine, or the auth store) may simply never have been used, so its
    ``_ensure_schema()`` never ran. Absent means zero rows to migrate, not an
    error.

    Args:
        conn: Open ``sqlite3.Connection``.
        table: Table name.

    Returns:
        ``True`` if the table is present.
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def source_columns(conn: Any, table: str) -> list[SourceColumn]:
    """Return a SQLite table's columns in declaration order.

    Args:
        conn: Open ``sqlite3.Connection``.
        table: Table name (trusted — always drawn from
            :data:`~backend.persistence.sqlite_to_postgres.tables.TABLE_COPY_ORDER`
            or ``sqlite_master``, never external input).

    Returns:
        Columns in the order SQLite reports them, matching row-tuple order
        from a ``SELECT * FROM table``.
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [SourceColumn(name=row[1]) for row in rows]


def dest_columns(conn: Any, table: str) -> dict[str, DestColumn]:
    """Return a PostgreSQL table's columns, keyed by name.

    Args:
        conn: Open psycopg connection.
        table: Table name.

    Returns:
        ``{column_name: DestColumn}`` for every column PostgreSQL reports
        for *table* in the connected database's default schema (``public``
        unless overridden). Empty if the table does not exist.
    """
    rows = conn.execute(
        "SELECT column_name, data_type, column_default "
        "FROM information_schema.columns WHERE table_name = %s",
        (table,),
    ).fetchall()
    return {
        row[0]: DestColumn(
            name=row[0],
            is_jsonb=(row[1] == "jsonb"),
            is_boolean=(row[1] == "boolean"),
            is_serial=bool(row[2] and str(row[2]).startswith("nextval(")),
            is_timestamp=row[1] in ("timestamp with time zone", "timestamp without time zone"),
        )
        for row in rows
    }


def dest_table_exists(conn: Any, table: str) -> bool:
    """Whether *table* exists in the connected PostgreSQL database.

    Args:
        conn: Open psycopg connection.
        table: Table name.

    Returns:
        ``True`` if the table is present.
    """
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
        (table,),
    ).fetchone()
    return row is not None


def dest_row_count(conn: Any, table: str) -> int:
    """Return the number of rows currently in a PostgreSQL table.

    Args:
        conn: Open psycopg connection.
        table: Table name (trusted, see :func:`source_columns`).

    Returns:
        Row count.
    """
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608 - trusted table name
    return int(row[0])


def source_row_count(conn: Any, table: str) -> int:
    """Return the number of rows currently in a SQLite table.

    Args:
        conn: Open ``sqlite3.Connection``.
        table: Table name (trusted, see :func:`source_columns`).

    Returns:
        Row count.
    """
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608 - trusted table name
    return int(row[0])


def collect_source_tenants(conn: Any) -> set[str]:
    """Collect every distinct ``tenant_id`` value present in the source database.

    Any read of a destination table under Row-Level Security must be scoped
    to a real tenant first: a ``FORCE``d table hides every row from a plain,
    unscoped ``SELECT`` (the connecting role is the table owner, which
    ``FORCE`` deliberately does not exempt from RLS) -- an unscoped read
    would silently see zero rows even when the table is fully populated.
    Both :mod:`backend.persistence.sqlite_to_postgres.preflight` (the
    "destination already has data" check) and
    :mod:`backend.persistence.sqlite_to_postgres.reconcile` (the
    destination-side row read) need this same tenant set for that reason.

    Args:
        conn: Open source ``sqlite3.Connection``.

    Returns:
        Every tenant id found in a tenant-scoped source table, plus
        :data:`~backend.persistence.tenancy.DEFAULT_TENANT_ID`.
    """
    tenants = {DEFAULT_TENANT_ID}
    for table in TABLE_COPY_ORDER:
        if not source_table_exists(conn, table):
            continue
        columns = {c.name for c in source_columns(conn, table)}
        if "tenant_id" not in columns:
            continue
        rows = conn.execute(f"SELECT DISTINCT tenant_id FROM {table}").fetchall()  # noqa: S608 - trusted table name
        tenants.update(row[0] for row in rows if row[0])
    return tenants


__all__ = [
    "DestColumn",
    "SourceColumn",
    "collect_source_tenants",
    "dest_columns",
    "dest_row_count",
    "dest_table_exists",
    "source_columns",
    "source_row_count",
    "source_table_exists",
    "source_table_names",
]
