"""Incremental run-step persistence regression tests (E44-S5).

Every ``update_run`` used to delete a run's whole ``run_steps`` list and
re-insert it, so a run that checkpoints after each of N steps wrote O(N^2)
rows. Steps are now upserted on their ``(run_id, position)`` key and skipped
entirely when unchanged, so the Nth checkpoint writes one row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.persistence.postgres_adapter import PostgresStore
from backend.persistence.sqlite_adapter import SQLiteStore

from backend.tests.unit.persistence.e44_helpers import rows_written
from backend.tests.unit.persistence.test_postgres_adapter import ScriptedConnection


@pytest.fixture
def sqlite_store(tmp_path: Path) -> SQLiteStore:
    """Build a :class:`SQLiteStore` with one seeded session and run."""
    target = SQLiteStore(database_url=f"sqlite:///{tmp_path / 'e44-s5.db'}")
    target.create_session(session_id="s1", goal="g", plan=[], artifacts={})
    target.create_run(
        run_id="r1",
        session_id="s1",
        status="running",
        run_type="auto",
        current_state="starting",
        trigger_message="go",
        results=[],
        steps=[],
    )
    return target


def _step(index: int, *, status: str = "completed") -> dict[str, Any]:
    """Build one step record at *index*."""
    return {
        "step_key": f"task-{index}",
        "agent": "coder",
        "status": status,
        "started_at": f"t{index}",
        "completed_at": f"t{index}+1",
        "attempt": 1,
    }


def _checkpoint(target: SQLiteStore, steps: list[dict[str, Any]]) -> None:
    """Persist *steps* as the run's current step list."""
    target.update_run(
        run_id="r1", status="running", current_state="working", results=[], steps=list(steps)
    )


def test_checkpointing_a_new_step_writes_one_row(sqlite_store: SQLiteStore) -> None:
    """The Nth checkpoint writes a single row, not N (E44-S5)."""
    steps = [_step(i) for i in range(30)]
    _checkpoint(sqlite_store, steps)

    steps.append(_step(30))
    written = rows_written(sqlite_store, lambda: _checkpoint(sqlite_store, steps))

    # One new run_steps row; the 30 unchanged upserts and the no-op trim
    # delete write nothing. (The runs row UPDATE is counted too.)
    assert written == 2


def test_repeated_identical_checkpoints_write_no_step_rows(sqlite_store: SQLiteStore) -> None:
    """Re-persisting an unchanged step list touches no step rows at all."""
    steps = [_step(i) for i in range(10)]
    _checkpoint(sqlite_store, steps)

    written = rows_written(sqlite_store, lambda: _checkpoint(sqlite_store, steps))

    assert written == 1  # the runs row only


def test_total_writes_are_linear_over_a_multi_checkpoint_run(
    sqlite_store: SQLiteStore,
) -> None:
    """A run checkpointing after each of N steps writes O(N) rows, not O(N^2)."""
    step_count = 40
    steps: list[dict[str, Any]] = []

    def run() -> None:
        for index in range(step_count):
            steps.append(_step(index))
            _checkpoint(sqlite_store, steps)

    written = rows_written(sqlite_store, run)

    # One step row plus one runs row per checkpoint. The old delete-and-
    # reinsert path wrote sum(2N) ~ 1600 step rows for the same run.
    assert written == 2 * step_count
    assert len(sqlite_store.list_run_steps("r1")) == step_count


def test_step_contents_and_order_survive_incremental_persistence(
    sqlite_store: SQLiteStore,
) -> None:
    """Incremental writes converge on exactly the list that was handed in."""
    steps = [_step(i, status="running") for i in range(5)]
    _checkpoint(sqlite_store, steps)

    steps[2] = _step(2, status="failed")
    steps.append(_step(5))
    _checkpoint(sqlite_store, steps)

    stored = sqlite_store.list_run_steps("r1")
    assert [row["step_key"] for row in stored] == [f"task-{i}" for i in range(6)]
    assert stored[2]["status"] == "failed"


def test_a_shortened_step_list_trims_the_surplus(sqlite_store: SQLiteStore) -> None:
    """Dropping steps (e.g. an awaiting_approval placeholder) removes their rows."""
    _checkpoint(sqlite_store, [_step(i) for i in range(6)])

    _checkpoint(sqlite_store, [_step(i) for i in range(3)])

    stored = sqlite_store.list_run_steps("r1")
    assert [row["step_key"] for row in stored] == ["task-0", "task-1", "task-2"]


def test_clearing_all_steps_removes_every_row(sqlite_store: SQLiteStore) -> None:
    """An empty step list leaves no rows behind."""
    _checkpoint(sqlite_store, [_step(i) for i in range(4)])

    _checkpoint(sqlite_store, [])

    assert sqlite_store.list_run_steps("r1") == []


def test_replace_for_import_rewrites_the_whole_list(sqlite_store: SQLiteStore) -> None:
    """The named full-replace path is still available for import/recovery."""
    _checkpoint(sqlite_store, [_step(i) for i in range(4)])

    sqlite_store.replace_run_steps_for_import("r1", [_step(9)])

    assert [row["step_key"] for row in sqlite_store.list_run_steps("r1")] == ["task-9"]


def test_replace_for_import_ignores_other_tenants_runs(sqlite_store: SQLiteStore) -> None:
    """A run outside the caller's tenant is left untouched."""
    _checkpoint(sqlite_store, [_step(0)])

    sqlite_store.replace_run_steps_for_import("r1", [], tenant_id="other")

    assert len(sqlite_store.list_run_steps("r1")) == 1


def test_postgres_checkpoint_issues_one_trim_and_one_upsert(
    pg_store: PostgresStore, pg_conn: ScriptedConnection
) -> None:
    """Postgres persists a checkpoint as a bounded trim plus one batched upsert."""
    pg_store.update_run(
        run_id="r1",
        status="running",
        current_state="working",
        results=[],
        steps=[_step(0), _step(1)],
    )

    deletes = [(sql, params) for sql, params in pg_conn.executed if "DELETE FROM run_steps" in sql]
    assert len(deletes) == 1
    assert deletes[0][1] == ("r1", 2)
    batched = [(sql, rows) for sql, rows in pg_conn.executed_many if "INSERT INTO run_steps" in sql]
    assert len(batched) == 1
    assert [row[1] for row in batched[0][1]] == [0, 1]
