"""Ordered, idempotent row copy for the SQLite -> PostgreSQL migration (E58-S2).

:func:`copy_all_tables` is schema-introspection-driven (see
:mod:`backend.persistence.sqlite_to_postgres.introspect`) rather than
hand-listing every column of every table: it reads the source's column order
via ``PRAGMA table_info`` and the destination's column types/defaults via
``information_schema.columns``, and uses that to build each table's
``INSERT`` statement, decide which columns need a ``::jsonb`` cast or a
``bool()`` coercion, and which columns need their PostgreSQL sequence
advanced afterward.

Idempotency (E58-S4-T1) comes from a single mechanism used everywhere: every
insert is ``ON CONFLICT DO NOTHING`` with no explicit conflict target (it
matches any unique/primary-key arbiter PostgreSQL finds), so re-running the
copy after an interruption — or a full re-run after completion — writes
nothing new for rows already present and is always safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from backend.persistence.tenancy import DEFAULT_TENANT_ID, set_postgres_tenant
from backend.persistence.sqlite_to_postgres.introspect import (
    DestColumn,
    dest_columns,
    source_columns,
    source_table_exists,
)
from backend.persistence.sqlite_to_postgres.tables import TABLE_COPY_ORDER

#: Number of source rows read per batch. Keeps memory bounded for large
#: tables instead of loading an entire table's rows at once.
_BATCH_SIZE = 1000

#: Progress callback: ``(table, rows_copied_so_far)``, called after each
#: batch (E58's "progress indicator per table for long migrations").
ProgressCallback = Callable[[str, int], None]


@dataclass(frozen=True)
class TableCopyResult:
    """Outcome of copying one table.

    Attributes:
        table: Table name.
        rows_read: Rows read from the source (attempted inserts — a retried
            row already present at the destination is read again but not
            re-inserted, per ``ON CONFLICT DO NOTHING``).
        sequence_adjusted: Column names whose PostgreSQL sequence was
            advanced past the migrated maximum (E58-S2-T2).
    """

    table: str
    rows_read: int
    sequence_adjusted: tuple[str, ...] = ()


def _build_insert_sql(table: str, columns: list[str], dest_cols: dict[str, DestColumn]) -> str:
    """Build the ``INSERT ... ON CONFLICT DO NOTHING`` statement for a table.

    Args:
        table: Table name.
        columns: Source column names, in the order row tuples will provide
            values.
        dest_cols: Destination column metadata, keyed by name.

    Returns:
        A parameterized ``INSERT`` statement with one ``%s`` (optionally
        ``::jsonb``-cast) placeholder per column.
    """
    placeholders = []
    for name in columns:
        cast = "::jsonb" if dest_cols.get(name, DestColumn(name, False, False, False)).is_jsonb else ""
        placeholders.append(f"%s{cast}")
    column_list = ", ".join(columns)
    placeholder_list = ", ".join(placeholders)
    return (
        f"INSERT INTO {table} ({column_list}) VALUES ({placeholder_list}) "
        "ON CONFLICT DO NOTHING"
    )


def _coerce_row(
    row: tuple[Any, ...], columns: list[str], dest_cols: dict[str, DestColumn]
) -> tuple[Any, ...]:
    """Coerce a source row's values for insertion into PostgreSQL.

    Only booleans need coercion: SQLite stores them as ``0``/``1`` integers,
    which a driver binds as integers, and PostgreSQL rejects an integer
    parameter into a ``boolean`` column. JSON text needs no Python-side
    transform — SQLite already stores valid JSON text, and the ``::jsonb``
    cast in the statement (see :func:`_build_insert_sql`) does the rest.

    Args:
        row: Source row, positional per *columns*.
        columns: Column names in *row*'s order.
        dest_cols: Destination column metadata, keyed by name.

    Returns:
        The row with boolean-typed values coerced; ``NULL`` passes through
        unchanged.
    """
    values = list(row)
    for index, name in enumerate(columns):
        dest = dest_cols.get(name)
        if dest is not None and dest.is_boolean and values[index] is not None:
            values[index] = bool(values[index])
    return tuple(values)


def _tenant_index(columns: list[str]) -> int | None:
    """Index of the ``tenant_id`` column within *columns*, if present."""
    return columns.index("tenant_id") if "tenant_id" in columns else None


def _insert_batch(
    dest_conn: Any,
    insert_sql: str,
    rows: list[tuple[Any, ...]],
    tenant_index: int | None,
) -> None:
    """Insert one batch of already-coerced rows, scoped per tenant when applicable.

    Rows are grouped by their ``tenant_id`` value (preserving relative
    order) so :func:`~backend.persistence.tenancy.set_postgres_tenant` is
    called once per distinct tenant present in the batch before its rows are
    inserted — required for tables with Row-Level Security enforced
    (``FORCE ROW LEVEL SECURITY``), and harmless for tables without it.

    Args:
        dest_conn: Open destination psycopg connection, inside an open
            transaction.
        insert_sql: Statement built by :func:`_build_insert_sql`.
        rows: Coerced rows to insert.
        tenant_index: Index of the ``tenant_id`` value within each row, or
            ``None`` for a table with no ``tenant_id`` column.
    """
    if tenant_index is None:
        with dest_conn.cursor() as cur:
            cur.executemany(insert_sql, rows)
        return

    groups: dict[str, list[tuple[Any, ...]]] = {}
    for row in rows:
        tenant_id = row[tenant_index] or DEFAULT_TENANT_ID
        groups.setdefault(tenant_id, []).append(row)
    for tenant_id, tenant_rows in groups.items():
        set_postgres_tenant(dest_conn, tenant_id)
        with dest_conn.cursor() as cur:
            cur.executemany(insert_sql, tenant_rows)


def copy_table(
    source_conn: Any,
    dest_conn: Any,
    table: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> TableCopyResult:
    """Copy one table's rows from the source to the destination, in batches.

    Commits the destination transaction once, after every batch for this
    table has been inserted and its sequence (if any) adjusted — so a table
    either migrates completely or (on an interruption) not at all, and a
    resumed run only re-attempts tables whose commit never happened
    (harmlessly re-attempting already-committed ones too, since every insert
    is ``ON CONFLICT DO NOTHING``).

    Args:
        source_conn: Open source ``sqlite3.Connection``, ideally inside a
            long-lived read transaction started before the whole copy pass
            (see :func:`copy_all_tables`) so every table is read from one
            consistent snapshot.
        dest_conn: Open destination psycopg connection.
        table: Table name.
        on_progress: Optional callback invoked after each batch with
            ``(table, rows_copied_so_far)``.

    Returns:
        The copy outcome for this table.
    """
    if not source_table_exists(source_conn, table):
        return TableCopyResult(table=table, rows_read=0)

    columns = [c.name for c in source_columns(source_conn, table)]
    dest_cols = dest_columns(dest_conn, table)
    insert_sql = _build_insert_sql(table, columns, dest_cols)
    tenant_index = _tenant_index(columns)

    cursor = source_conn.execute(f"SELECT {', '.join(columns)} FROM {table}")  # noqa: S608 - trusted table/column names
    rows_read = 0
    while True:
        batch = cursor.fetchmany(_BATCH_SIZE)
        if not batch:
            break
        coerced = [_coerce_row(tuple(row), columns, dest_cols) for row in batch]
        _insert_batch(dest_conn, insert_sql, coerced, tenant_index)
        rows_read += len(batch)
        if on_progress is not None:
            on_progress(table, rows_read)

    sequence_adjusted = _adjust_sequences(dest_conn, table, dest_cols)
    dest_conn.commit()
    return TableCopyResult(table=table, rows_read=rows_read, sequence_adjusted=sequence_adjusted)


def _adjust_sequences(
    dest_conn: Any, table: str, dest_cols: dict[str, DestColumn]
) -> tuple[str, ...]:
    """Advance every sequence-backed column's sequence past the migrated maximum.

    Prevents the classic post-migration defect: a sequence left at its
    initial value would generate identifiers colliding with rows just
    migrated (E58-S2-T2). Uses ``pg_get_serial_sequence`` so no sequence
    name needs to be guessed or hardcoded.

    Args:
        dest_conn: Open destination psycopg connection.
        table: Table name.
        dest_cols: Destination column metadata, keyed by name.

    Returns:
        Names of the columns whose sequence was adjusted.
    """
    adjusted = []
    for column in dest_cols.values():
        if not column.is_serial:
            continue
        with dest_conn.cursor() as cur:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence(%s, %s), "  # noqa: S608 - table/column passed as bound params, not interpolated
                f"COALESCE((SELECT MAX({column.name}) FROM {table}), 1), "
                f"(SELECT MAX({column.name}) FROM {table}) IS NOT NULL)",
                (table, column.name),
            )
        adjusted.append(column.name)
    return tuple(adjusted)


def copy_all_tables(
    source_conn: Any,
    dest_conn: Any,
    *,
    on_progress: ProgressCallback | None = None,
) -> tuple[TableCopyResult, ...]:
    """Copy every table in :data:`TABLE_COPY_ORDER`, in dependency order.

    Opens one read transaction on the source spanning the whole pass, so
    every table (across the entire copy, not just within one table) is read
    from a single consistent snapshot rather than a moving target — even
    though each table's destination write commits independently (see
    :func:`copy_table`).

    Args:
        source_conn: Open source ``sqlite3.Connection``.
        dest_conn: Open destination psycopg connection, with its schema
            already applied (ADR-026 decision 5 — this function never
            creates a table).
        on_progress: Forwarded to :func:`copy_table` for every table.

    Returns:
        One :class:`TableCopyResult` per table in :data:`TABLE_COPY_ORDER`.
    """
    dest_conn.execute("SET TIME ZONE 'UTC'")
    source_conn.execute("BEGIN DEFERRED")
    try:
        return tuple(
            copy_table(source_conn, dest_conn, table, on_progress=on_progress)
            for table in TABLE_COPY_ORDER
        )
    finally:
        # Read-only transaction: nothing to commit. Rollback releases the
        # snapshot without touching the source (ADR-026 decision 2).
        source_conn.rollback()


__all__ = ["ProgressCallback", "TableCopyResult", "copy_all_tables", "copy_table"]
