"""Preflight checks for the SQLite -> PostgreSQL migration (E58-S1-T2).

Every check here is read-only on both databases: it never applies a
migration, never creates a table, and never writes a row. ``--dry-run``
(:mod:`backend.persistence.sqlite_to_postgres.plan`) builds directly on this
module's :class:`PreflightReport`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.persistence.contract import is_postgres
from backend.persistence.migrations.versions import PLAN_STORE_MIGRATIONS, STORE_MIGRATIONS
from backend.persistence.sqlite_to_postgres.connections import (
    open_dest_connection,
    open_source_connection,
    redact_url,
)
from backend.persistence.sqlite_to_postgres.introspect import (
    collect_source_tenants,
    dest_columns,
    source_table_names,
)
from backend.persistence.sqlite_to_postgres.tables import IGNORED_SQLITE_TABLES, TABLE_COPY_ORDER
from backend.persistence.tenancy import DEFAULT_TENANT_ID, set_postgres_tenant
from backend.plans.step_state import legacy_step_state_db_path

#: (namespace, known-migration-count) pairs the versioned SQLite migration
#: runner tracks. "Same schema version" (ADR-026 decision 4) is interpreted
#: per-backend: the source must be fully up to date against *its own*
#: migration list, because the SQLite and PostgreSQL migration lists have
#: independently grown to different lengths for equivalent schema state (the
#: PostgreSQL list has fewer entries per feature; see
#: ``backend/persistence/migrations/postgres_versions.py``'s module
#: docstring). The destination is never behind: its schema is created fresh
#: by the current code (ADR-026 decision 5), so only the source can be stale.
_SQLITE_NAMESPACES: tuple[tuple[str, int], ...] = (
    ("store", len(STORE_MIGRATIONS)),
    ("plan_store", len(PLAN_STORE_MIGRATIONS)),
)


@dataclass(frozen=True)
class PreflightReport:
    """Outcome of a full preflight pass.

    Attributes:
        source_url: Redacted source URL (never the raw credential-bearing URL).
        dest_url: Redacted destination URL.
        errors: Problems that must block the migration. Empty means preflight
            passed.
        warnings: Problems worth surfacing but that do not block the
            migration.
        source_schema_versions: ``{namespace: (current, known)}`` read from
            the source's ``schema_version`` table.
        unknown_source_tables: Tables present in the source database that
            this migrator does not know how to move — always an error when
            non-empty (schema-drift safety net, see
            :mod:`backend.persistence.sqlite_to_postgres.tables`).
        destination_has_data: Whether the destination already contains rows
            in a known table.
        step_state_file: Path to the legacy standalone plan-step-state file,
            if it exists on disk; ``None`` otherwise.
        vector_extension_available: Whether PostgreSQL's ``vector`` extension
            is already installed or at least available to install.
    """

    source_url: str
    dest_url: str
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    source_schema_versions: dict[str, tuple[int, int]] = field(default_factory=dict)
    unknown_source_tables: tuple[str, ...] = field(default_factory=tuple)
    destination_has_data: bool = False
    step_state_file: str | None = None
    vector_extension_available: bool = True

    @property
    def passed(self) -> bool:
        """Whether the migration may proceed."""
        return not self.errors


def _check_source_schema_versions(
    conn: Any, errors: list[str]
) -> dict[str, tuple[int, int]]:
    """Read and validate the source's ``schema_version`` rows.

    Args:
        conn: Open source ``sqlite3.Connection``.
        errors: Appended to in place on a version mismatch.

    Returns:
        ``{namespace: (current, known)}`` for every namespace this migrator
        tracks.
    """
    versions: dict[str, tuple[int, int]] = {}
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    for namespace, known in _SQLITE_NAMESPACES:
        row = None
        if table_exists is not None:
            row = conn.execute(
                "SELECT version FROM schema_version WHERE namespace = ?", (namespace,)
            ).fetchone()
        if row is None:
            # No row for this namespace at all means its store was never
            # constructed against this database -- that subsystem is simply
            # unused (e.g. the plans subsystem on an install that never
            # created a plan), exactly like a self-managed store whose
            # tables were never created. Nothing to migrate, not a staleness
            # problem.
            versions[namespace] = (0, known)
            continue
        current = row[0]
        versions[namespace] = (current, known)
        if current != known:
            errors.append(
                f"source schema namespace {namespace!r} is at version {current}, "
                f"but this install's code is at version {known}. Run `autodev upgrade` "
                "against the source before migrating, or update this install."
            )
    return versions


def _check_table_inventory(conn: Any, errors: list[str]) -> tuple[str, ...]:
    """Diff the source's actual tables against :data:`TABLE_COPY_ORDER`.

    Args:
        conn: Open source ``sqlite3.Connection``.
        errors: Appended to in place when an unknown table is found.

    Returns:
        The unknown table names, if any.
    """
    actual = set(source_table_names(conn)) - IGNORED_SQLITE_TABLES
    unknown = tuple(sorted(actual - set(TABLE_COPY_ORDER)))
    if unknown:
        errors.append(
            "source database has tables this migrator does not know how to move: "
            f"{', '.join(unknown)}. Refusing to proceed rather than silently drop data — "
            "update backend/persistence/sqlite_to_postgres/tables.py."
        )
    return unknown


def _check_destination(conn: Any, source_tenants: set[str], errors: list[str]) -> bool:
    """Check destination reachability and whether it already has data.

    Args:
        conn: Open destination psycopg connection.
        source_tenants: Tenants to check tenant-scoped tables under (see
            :func:`~backend.persistence.sqlite_to_postgres.introspect.collect_source_tenants`)
            -- an unscoped read would miss every row on a
            Row-Level-Security-protected table.
        errors: Unused for now (reserved for reachability failures raised as
            exceptions upstream); kept for signature symmetry.

    Returns:
        Whether any known table exists in the destination and has at least
        one row visible under any of *source_tenants*, or (for tables with
        no ``tenant_id`` column, hence no RLS) at all.
    """
    del errors
    existing_tables = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = ANY(%s)",
            (list(TABLE_COPY_ORDER),),
        ).fetchall()
    }
    for table in existing_tables:
        dest_cols = dest_columns(conn, table)
        if "tenant_id" not in dest_cols:
            row = conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()  # noqa: S608 - trusted table name
            if row is not None:
                return True
            continue
        for tenant_id in source_tenants:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()  # noqa: S608 - trusted table name
            if row is not None:
                return True
    return False


def _check_vector_extension(conn: Any) -> bool:
    """Whether PostgreSQL's ``vector`` extension is installed or installable.

    Args:
        conn: Open destination psycopg connection.

    Returns:
        ``True`` if the extension is already installed, or listed as
        available to install.
    """
    installed = conn.execute(
        "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
    ).fetchone()
    if installed is not None:
        return True
    available = conn.execute(
        "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
    ).fetchone()
    return available is not None


def run_preflight(
    source_url: str, dest_url: str, *, confirm_nonempty_destination: bool = False
) -> PreflightReport:
    """Run every E58-S1-T2 preflight check.

    Args:
        source_url: Source ``sqlite://`` URL.
        dest_url: Destination ``postgresql://`` URL.
        confirm_nonempty_destination: When ``True``, a destination that
            already has data is a warning instead of a blocking error — the
            operator's explicit acknowledgement required by ADR-026 decision
            4 ("destination empty or explicitly confirmed").

    Returns:
        The full preflight report. Check :attr:`PreflightReport.passed`
        before proceeding.
    """
    errors: list[str] = []
    warnings: list[str] = []
    source_versions: dict[str, tuple[int, int]] = {}
    unknown_tables: tuple[str, ...] = ()
    source_tenants: set[str] = {DEFAULT_TENANT_ID}
    destination_has_data = False
    vector_available = True

    if not is_postgres(dest_url):
        errors.append(f"--to must be a postgresql:// URL, got: {redact_url(dest_url)!r}")

    try:
        source_conn = open_source_connection(source_url)
    except FileNotFoundError as exc:
        errors.append(str(exc))
        source_conn = None

    if source_conn is not None:
        try:
            source_versions = _check_source_schema_versions(source_conn, errors)
            unknown_tables = _check_table_inventory(source_conn, errors)
            source_tenants = collect_source_tenants(source_conn)
        finally:
            source_conn.close()

    dest_conn = None
    if is_postgres(dest_url):
        try:
            dest_conn = open_dest_connection(dest_url)
        except Exception as exc:  # noqa: BLE001 - surfaced as a preflight error, any driver failure
            errors.append(f"destination unreachable: {exc}")

    if dest_conn is not None:
        try:
            destination_has_data = _check_destination(dest_conn, source_tenants, errors)
            vector_available = _check_vector_extension(dest_conn)
        finally:
            dest_conn.close()

    if destination_has_data:
        message = "destination already contains data in a known table"
        if confirm_nonempty_destination:
            warnings.append(f"{message} (proceeding: confirmed by operator)")
        else:
            errors.append(
                f"{message}. Pass --confirm-nonempty-destination to proceed anyway "
                "(existing rows are not removed; the copy is idempotent, see E58-S4-T1)."
            )

    if not vector_available:
        warnings.append(
            "PostgreSQL 'vector' extension is neither installed nor available to "
            "install on the destination — code_chunks/code_embeddings migration will "
            "fail applying the destination schema unless an operator installs it first."
        )

    step_state_path = legacy_step_state_db_path()
    step_state_file = str(step_state_path) if step_state_path.exists() else None
    if step_state_file:
        warnings.append(
            f"legacy standalone plan-step-state file detected: {step_state_file} "
            "(will be migrated by E58-S3-T1)"
        )

    return PreflightReport(
        source_url=redact_url(source_url),
        dest_url=redact_url(dest_url),
        errors=tuple(errors),
        warnings=tuple(warnings),
        source_schema_versions=source_versions,
        unknown_source_tables=unknown_tables,
        destination_has_data=destination_has_data,
        step_state_file=step_state_file,
        vector_extension_available=vector_available,
    )


__all__ = ["PreflightReport", "run_preflight"]
