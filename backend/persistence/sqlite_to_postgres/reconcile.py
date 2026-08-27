"""Per-table count and content reconciliation (E58-S3-T3).

Reconciliation is a gate, not a warning (ADR-026 decision 9): a row-count or
content mismatch fails the migration outright. Hashing happens entirely in
Python, never in SQL — cross-engine ``SELECT`` aggregation is not a safe
comparison here. SQLite and PostgreSQL render the same logical value
differently (``0``/``1`` vs ``t``/``f`` for booleans, JSON key order and
whitespace, timestamp formatting) and order rows differently (PostgreSQL's
collation vs SQLite's byte comparison), so even identical data can produce
different SQL-side aggregate hashes. Fetching rows on both sides, running one
canonicalizer, and comparing *sorted* per-row digest lists sidesteps both
problems.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from backend.persistence.sqlite_to_postgres.introspect import (
    DestColumn,
    collect_source_tenants,
    dest_columns,
    dest_table_exists,
    source_columns,
    source_table_exists,
)
from backend.persistence.sqlite_to_postgres.tables import TABLE_COPY_ORDER
from backend.persistence.tenancy import set_postgres_tenant

_NULL_SENTINEL = "\x00NULL\x00"
_BATCH_SIZE = 1000


@dataclass(frozen=True)
class TableReconciliation:
    """Reconciliation outcome for one table.

    Attributes:
        table: Table name.
        source_count: Row count read from the source.
        dest_count: Row count read from the destination.
        matched: Whether counts and every row's content digest matched.
        mismatched_digests: Number of source digests with no matching
            destination digest (order-independent — a value here means real
            content differs, not that rows merely came back in a different
            order).
    """

    table: str
    source_count: int
    dest_count: int
    matched: bool
    mismatched_digests: int = 0


@dataclass(frozen=True)
class ReconciliationReport:
    """Aggregate reconciliation outcome across every table.

    Attributes:
        tables: Per-table results, in :data:`TABLE_COPY_ORDER`.
    """

    tables: tuple[TableReconciliation, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """Whether every table reconciled cleanly — the cutover gate (ADR-026 decision 9)."""
        return all(t.matched for t in self.tables)


def _parse_timestamp(value: Any) -> str:
    """Normalize a timestamp value (SQLite text or PostgreSQL ``datetime``) to comparable ISO-UTC text.

    SQLite stores a timestamp as text in one of two formats depending on how
    it was written: ``CURRENT_TIMESTAMP``'s default (``YYYY-MM-DD HH:MM:SS``,
    space-separated, no offset, implicitly UTC) or application code's
    ``datetime.isoformat()`` (``T``-separated, with a ``+00:00`` offset).
    PostgreSQL returns a timezone-aware ``datetime.datetime``.

    Args:
        value: A timestamp value from either side.

    Returns:
        ``value``'s instant as ISO-8601 text in UTC, or the stringified
        value unchanged if it cannot be parsed as a timestamp (defensive:
        content still participates in the digest either way).
    """
    if isinstance(value, datetime.datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc).isoformat()
    text = str(value)
    normalized = text.replace(" ", "T", 1) if "T" not in text else text
    try:
        dt = datetime.datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat()


def _canonical_value(value: Any, column: DestColumn | None) -> str:
    """Render one column value as a canonical string for hashing.

    Args:
        value: The raw value read from either database.
        column: Destination column metadata for this column, or ``None`` for
            a column absent from the destination (its own mismatch, folded
            into the row's digest by canonicalizing as its raw string form).

    Returns:
        A canonical string: JSON re-serialized with sorted keys for jsonb
        columns, ``"true"``/``"false"`` for boolean columns, ISO-UTC text
        for timestamp columns (see :func:`_parse_timestamp`), a null
        sentinel for ``NULL``, and ``str(value)`` otherwise.
    """
    if value is None:
        return _NULL_SENTINEL
    if column is not None and column.is_jsonb:
        parsed = json.loads(value) if isinstance(value, str) else value
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    if column is not None and column.is_boolean:
        return "true" if bool(value) else "false"
    if column is not None and column.is_timestamp:
        return _parse_timestamp(value)
    return str(value)


def _row_digest(row: tuple[Any, ...], columns: list[str], dest_cols: dict[str, DestColumn]) -> str:
    """Compute one row's SHA-256 content digest.

    Args:
        row: Row values, positional per *columns*.
        columns: Column names in *row*'s order.
        dest_cols: Destination column metadata, keyed by name.

    Returns:
        Hex-encoded SHA-256 digest of the row's canonicalized values, joined
        by a separator that cannot appear in any canonical value.
    """
    canonical = [_canonical_value(value, dest_cols.get(name)) for name, value in zip(columns, row)]
    return hashlib.sha256("\x1f".join(canonical).encode("utf-8")).hexdigest()


def _source_digests(conn: Any, table: str, columns: list[str], dest_cols: dict[str, DestColumn]) -> list[str]:
    """Compute every source row's content digest for one table."""
    cursor = conn.execute(f"SELECT {', '.join(columns)} FROM {table}")  # noqa: S608 - trusted table/column names
    digests: list[str] = []
    while True:
        batch = cursor.fetchmany(_BATCH_SIZE)
        if not batch:
            break
        digests.extend(_row_digest(tuple(row), columns, dest_cols) for row in batch)
    return digests


def _dest_digests(
    conn: Any, table: str, columns: list[str], dest_cols: dict[str, DestColumn], tenants: set[str]
) -> list[str]:
    """Compute every destination row's content digest for one table.

    Row-Level Security on a ``FORCE``d table hides every row from a plain,
    unscoped ``SELECT`` regardless of its actual contents (the connecting
    role is the table owner, which ``FORCE`` deliberately does not exempt).
    A table with no ``tenant_id`` column has no RLS policy to worry about
    and is read once, unscoped; a tenant-scoped table is read once per
    tenant in *tenants*, with :func:`~backend.persistence.tenancy.set_postgres_tenant`
    setting the session's tenant before each.

    Args:
        conn: Open destination psycopg connection.
        table: Table name.
        columns: Column names to select, in source order.
        dest_cols: Destination column metadata, keyed by name.
        tenants: Every tenant to check, when *table* has a ``tenant_id``
            column (see :func:`~backend.persistence.sqlite_to_postgres.introspect.collect_source_tenants`).

    Returns:
        One digest per destination row visible across *tenants* (or all rows,
        for a table with no ``tenant_id`` column).
    """
    digests: list[str] = []
    scopes: list[str | None] = [None] if "tenant_id" not in dest_cols else list(tenants)
    for tenant_id in scopes:
        if tenant_id is not None:
            set_postgres_tenant(conn, tenant_id)
        with conn.cursor() as cur:
            cur.execute(f"SELECT {', '.join(columns)} FROM {table}")  # noqa: S608 - trusted table/column names
            while True:
                batch = cur.fetchmany(_BATCH_SIZE)
                if not batch:
                    break
                digests.extend(_row_digest(tuple(row), columns, dest_cols) for row in batch)
    return digests


def _dest_count(conn: Any, table: str, dest_cols: dict[str, DestColumn], tenants: set[str]) -> int:
    """Count destination rows for one table, scoped the same way as :func:`_dest_digests`."""
    if "tenant_id" not in dest_cols:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 - trusted table name
    total = 0
    for tenant_id in tenants:
        set_postgres_tenant(conn, tenant_id)
        total += int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 - trusted table name
    return total


def reconcile_table(source_conn: Any, dest_conn: Any, table: str, tenants: set[str]) -> TableReconciliation:
    """Reconcile one table: row counts and, if they match, per-row content digests.

    Args:
        source_conn: Open source ``sqlite3.Connection``.
        dest_conn: Open destination psycopg connection.
        table: Table name.
        tenants: Every tenant present in the source (see
            :func:`~backend.persistence.sqlite_to_postgres.introspect.collect_source_tenants`),
            used to scope destination reads on Row-Level-Security-protected
            tables.

    Returns:
        The reconciliation outcome. A count mismatch short-circuits before
        the (more expensive) digest comparison, since counts already prove a
        mismatch either way.
    """
    source_exists = source_table_exists(source_conn, table)
    dest_exists = dest_table_exists(dest_conn, table)
    dest_cols = dest_columns(dest_conn, table) if dest_exists else {}
    if not source_exists or not dest_exists:
        source_count = 0
        if source_exists:
            source_count = int(source_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 - trusted table name
        dest_count = _dest_count(dest_conn, table, dest_cols, tenants) if dest_exists else 0
        return TableReconciliation(
            table=table,
            source_count=source_count,
            dest_count=dest_count,
            matched=(source_count == 0 and dest_count == 0),
        )

    columns = [c.name for c in source_columns(source_conn, table)]

    source_digests = sorted(_source_digests(source_conn, table, columns, dest_cols))
    dest_digests = sorted(_dest_digests(dest_conn, table, columns, dest_cols, tenants))

    if len(source_digests) != len(dest_digests):
        return TableReconciliation(
            table=table,
            source_count=len(source_digests),
            dest_count=len(dest_digests),
            matched=False,
        )

    mismatched = sum(1 for a, b in zip(source_digests, dest_digests) if a != b)
    return TableReconciliation(
        table=table,
        source_count=len(source_digests),
        dest_count=len(dest_digests),
        matched=(mismatched == 0),
        mismatched_digests=mismatched,
    )


def reconcile_all_tables(source_conn: Any, dest_conn: Any) -> ReconciliationReport:
    """Reconcile every table in :data:`TABLE_COPY_ORDER`.

    Args:
        source_conn: Open source ``sqlite3.Connection``.
        dest_conn: Open destination psycopg connection.

    Returns:
        The full reconciliation report. Check
        :attr:`ReconciliationReport.passed` before treating a migration as
        complete — cutover must not proceed without a clean report (ADR-026
        decision 9).
    """
    tenants = collect_source_tenants(source_conn)
    return ReconciliationReport(
        tables=tuple(
            reconcile_table(source_conn, dest_conn, table, tenants) for table in TABLE_COPY_ORDER
        )
    )


__all__ = [
    "ReconciliationReport",
    "TableReconciliation",
    "reconcile_all_tables",
    "reconcile_table",
]
