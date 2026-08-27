"""Dry-run planning for the SQLite -> PostgreSQL migration (E58-S1-T3).

Builds a complete migration plan — every table that would be copied and how
many rows each has — without writing anything to either database. Column-set
comparison against the destination is best-effort: when the destination has
no schema yet (the common dry-run case, since applying the destination
schema is itself a write), those checks are simply not run and the plan says
so rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.persistence.sqlite_to_postgres.connections import (
    open_dest_connection,
    open_source_connection,
)
from backend.persistence.sqlite_to_postgres.introspect import (
    dest_columns,
    dest_row_count,
    dest_table_exists,
    source_columns,
    source_row_count,
    source_table_exists,
)
from backend.persistence.sqlite_to_postgres.preflight import PreflightReport, run_preflight
from backend.persistence.sqlite_to_postgres.tables import TABLE_COPY_ORDER


@dataclass(frozen=True)
class TablePlan:
    """The planned copy for one table.

    Attributes:
        table: Table name.
        source_rows: Row count in the source at plan time.
        dest_rows: Row count already in the destination, or ``None`` when the
            destination table does not exist yet (schema not applied).
        missing_dest_columns: Source columns with no matching destination
            column — would silently lose data if copied as-is; a non-empty
            list here is always a preflight-blocking problem when it occurs
            against an already-applied destination schema, and is left for
            the operator to investigate before ``--dry-run`` promises the
            move is safe.
    """

    table: str
    source_rows: int
    dest_rows: int | None
    missing_dest_columns: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MigrationPlan:
    """A complete dry-run plan: nothing written, everything reported.

    Attributes:
        preflight: The preflight report this plan was built from.
        tables: Per-table plans, in copy order.
        destination_schema_applied: Whether the destination already has a
            schema to compare against (``False`` means column-set checks
            were skipped and will only run at apply time).
    """

    preflight: PreflightReport
    tables: tuple[TablePlan, ...]
    destination_schema_applied: bool

    @property
    def total_source_rows(self) -> int:
        """Sum of :attr:`TablePlan.source_rows` across every table."""
        return sum(t.source_rows for t in self.tables)


def build_dry_run_plan(
    source_url: str, dest_url: str, *, confirm_nonempty_destination: bool = False
) -> MigrationPlan:
    """Build a full migration plan, writing nothing to either database.

    Args:
        source_url: Source ``sqlite://`` URL.
        dest_url: Destination ``postgresql://`` URL.
        confirm_nonempty_destination: Forwarded to :func:`run_preflight`.

    Returns:
        The plan. Table-level counts are read even when preflight failed
        (e.g. a schema-version mismatch), so an operator can see the full
        picture of what a fixed installation would migrate; check
        :attr:`PreflightReport.passed` on :attr:`MigrationPlan.preflight`
        before treating the plan as actionable.
    """
    preflight = run_preflight(
        source_url, dest_url, confirm_nonempty_destination=confirm_nonempty_destination
    )

    table_plans: list[TablePlan] = []
    destination_schema_applied = False

    try:
        source_conn = open_source_connection(source_url)
    except FileNotFoundError:
        return MigrationPlan(
            preflight=preflight, tables=(), destination_schema_applied=False
        )

    dest_conn = None
    try:
        dest_conn = open_dest_connection(dest_url)
    except Exception:  # noqa: BLE001 - dry run degrades gracefully; preflight already reported this
        dest_conn = None

    try:
        for table in TABLE_COPY_ORDER:
            if not source_table_exists(source_conn, table):
                table_plans.append(TablePlan(table=table, source_rows=0, dest_rows=None))
                continue
            src_rows = source_row_count(source_conn, table)
            src_cols = {c.name for c in source_columns(source_conn, table)}

            dest_rows: int | None = None
            missing: tuple[str, ...] = ()
            if dest_conn is not None and dest_table_exists(dest_conn, table):
                destination_schema_applied = True
                dest_rows = dest_row_count(dest_conn, table)
                dest_cols = set(dest_columns(dest_conn, table).keys())
                missing = tuple(sorted(src_cols - dest_cols))

            table_plans.append(
                TablePlan(
                    table=table,
                    source_rows=src_rows,
                    dest_rows=dest_rows,
                    missing_dest_columns=missing,
                )
            )
    finally:
        source_conn.close()
        if dest_conn is not None:
            dest_conn.close()

    return MigrationPlan(
        preflight=preflight,
        tables=tuple(table_plans),
        destination_schema_applied=destination_schema_applied,
    )


__all__ = ["MigrationPlan", "TablePlan", "build_dry_run_plan"]
