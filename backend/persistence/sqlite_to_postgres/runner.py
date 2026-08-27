"""Top-level orchestration for the SQLite -> PostgreSQL migration (E58).

:func:`run_migration` is the one entry point ``autodev database migrate``
(without ``--dry-run``) calls: preflight, apply the destination schema, copy
every table, migrate the legacy step-state file, verify artifact pointers,
and reconcile -- in that order, stopping early (without reconciling, since
there is nothing meaningful to reconcile) if preflight refuses.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from backend.persistence.sqlite_to_postgres.artifacts import (
    DanglingArtifactPointer,
    find_dangling_artifact_pointers,
)
from backend.persistence.sqlite_to_postgres.connections import open_dest_connection, open_source_connection
from backend.persistence.sqlite_to_postgres.copy import ProgressCallback, TableCopyResult, copy_all_tables
from backend.persistence.sqlite_to_postgres.preflight import PreflightReport, run_preflight
from backend.persistence.sqlite_to_postgres.reconcile import ReconciliationReport, reconcile_all_tables
from backend.persistence.sqlite_to_postgres.step_state import migrate_step_state_to_destination
from backend.persistence.step_state_migration import StepStateMigrationReport


@dataclass(frozen=True)
class MigrationResult:
    """Outcome of a full ``autodev database migrate`` run.

    Attributes:
        preflight: The preflight report. If it did not pass, every other
            field is empty/default -- the migration never proceeded.
        copy_results: Per-table copy outcomes, in copy order.
        step_state: Legacy standalone plan-step-state file migration report.
        dangling_artifact_pointers: Migrated artifact pointers whose object
            does not resolve in the configured artifact store.
        reconciliation: Full per-table reconciliation report.
    """

    preflight: PreflightReport
    copy_results: tuple[TableCopyResult, ...] = field(default_factory=tuple)
    step_state: Optional[StepStateMigrationReport] = None
    dangling_artifact_pointers: tuple[DanglingArtifactPointer, ...] = field(default_factory=tuple)
    reconciliation: Optional[ReconciliationReport] = None

    @property
    def safe_to_cut_over(self) -> bool:
        """Whether reconciliation passed cleanly -- the cutover gate (ADR-026 decision 9)."""
        return bool(self.reconciliation and self.reconciliation.passed)

    def as_dict(self) -> dict:
        """Return this result as a JSON-serializable dict, for the persisted report."""
        return {
            "preflight": asdict(self.preflight),
            "copy_results": [asdict(r) for r in self.copy_results],
            "step_state": asdict(self.step_state) if self.step_state else None,
            "dangling_artifact_pointers": [asdict(p) for p in self.dangling_artifact_pointers],
            "reconciliation": asdict(self.reconciliation) if self.reconciliation else None,
            "safe_to_cut_over": self.safe_to_cut_over,
        }


def _apply_destination_schema(dest_url: str) -> None:
    """Materialize the full destination schema by constructing every domain store.

    Each store creates its own tables idempotently on construction (ADR-026
    decision 5: the destination schema is created by the normal migration
    runner, never by this migrator). Constructing them here, once, up front,
    means :func:`~backend.persistence.sqlite_to_postgres.copy.copy_all_tables`
    only ever needs to ``INSERT`` into tables that already exist.

    Args:
        dest_url: Destination PostgreSQL ``DATABASE_URL``.
    """
    from backend.artifacts.pointers import ArtifactPointerStore
    from backend.auth.store import AuthStore
    from backend.agents.registry_v2 import AgentRegistry
    from backend.events.store import EventStore
    from backend.flows.registry import FlowRegistry
    from backend.flows.state import FlowRunStore
    from backend.persistence.postgres_adapter import PostgresPlanStore, PostgresStore
    from backend.skills.registry_v2 import SkillRegistry

    dest_store = PostgresStore(dest_url)
    PostgresPlanStore(database_url=dest_url)
    ArtifactPointerStore(store=dest_store)
    EventStore(store=dest_store)
    FlowRunStore(store=dest_store)
    FlowRegistry(store=dest_store)
    AuthStore(store=dest_store)
    SkillRegistry(store=dest_store)
    AgentRegistry(store=dest_store)


def run_migration(
    source_url: str,
    dest_url: str,
    *,
    confirm_nonempty_destination: bool = False,
    report_path: Optional[Path] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> MigrationResult:
    """Run the full migration: preflight, schema, copy, step state, artifacts, reconcile.

    Safe to run more than once (E58-S4-T1): every table copy is
    ``ON CONFLICT DO NOTHING``, the legacy step-state migration is already
    idempotent (E55-S3), and reconciliation re-verifies the current state
    regardless of how many times the copy ran.

    Args:
        source_url: Source ``sqlite://`` URL.
        dest_url: Destination ``postgresql://`` URL.
        confirm_nonempty_destination: Forwarded to :func:`~backend.persistence.sqlite_to_postgres.preflight.run_preflight`.
        report_path: Where to persist the full result as JSON. Defaults to
            not persisting (callers such as the CLI pass an explicit path).
            Connection strings never appear in the report (preflight already
            redacts both URLs).
        on_progress: Forwarded to :func:`~backend.persistence.sqlite_to_postgres.copy.copy_all_tables`.

    Returns:
        The full migration result. Check :attr:`MigrationResult.preflight`'s
        ``passed`` property first -- every other field is empty when
        preflight refused.
    """
    preflight = run_preflight(
        source_url, dest_url, confirm_nonempty_destination=confirm_nonempty_destination
    )
    if not preflight.passed:
        result = MigrationResult(preflight=preflight)
        _persist_report(result, report_path)
        return result

    _apply_destination_schema(dest_url)

    source_conn = open_source_connection(source_url)
    dest_conn = open_dest_connection(dest_url)
    try:
        copy_results = copy_all_tables(source_conn, dest_conn, on_progress=on_progress)
    finally:
        source_conn.close()
        dest_conn.close()

    step_state_report = migrate_step_state_to_destination(dest_url)

    dest_conn = open_dest_connection(dest_url)
    try:
        from backend.artifacts.store import get_artifact_store

        dangling = find_dangling_artifact_pointers(dest_conn, get_artifact_store())
    finally:
        dest_conn.close()

    source_conn = open_source_connection(source_url)
    dest_conn = open_dest_connection(dest_url)
    try:
        reconciliation = reconcile_all_tables(source_conn, dest_conn)
    finally:
        source_conn.close()
        dest_conn.close()

    result = MigrationResult(
        preflight=preflight,
        copy_results=copy_results,
        step_state=step_state_report,
        dangling_artifact_pointers=dangling,
        reconciliation=reconciliation,
    )
    _persist_report(result, report_path)
    return result


def _persist_report(result: MigrationResult, report_path: Optional[Path]) -> None:
    """Write the full result to *report_path* as JSON, if given.

    Args:
        result: The migration result to persist.
        report_path: Destination file, or ``None`` to skip persisting.
    """
    if report_path is None:
        return
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result.as_dict(), indent=2, sort_keys=True), encoding="utf-8")


__all__ = ["MigrationResult", "run_migration"]
