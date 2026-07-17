"""Unit tests for backend/persistence/migrations/runner.py (E12-S1).

Covers :class:`MigrationRunner`'s full method surface against a real
in-memory SQLite connection: version-table bootstrap (including the legacy
single-column schema migration branch), ``run_pending``, ``rollback_to``
(including its ``ValueError`` branch), and ``run_down`` (including its
``ValueError`` branch). Also covers ``_as_migration``'s two branches (bare
callable vs. explicit :class:`Migration`) via ``run_pending``/``rollback_to``
behavior, since the normalization is internal and has no public surface of
its own.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest

from backend.persistence.migrations.runner import Migration, MigrationRunner


def _make_conn() -> sqlite3.Connection:
    """Return a fresh in-memory SQLite connection for a single test."""
    return sqlite3.connect(":memory:")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Return whether a table named *name* exists in *conn*'s schema."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def test_run_pending_applies_bare_callables_in_order() -> None:
    """Bare forward-only callables are normalized and applied in declared order."""
    conn = _make_conn()
    applied: list[str] = []

    def up_one(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE t1 (id INTEGER)")
        applied.append("one")

    def up_two(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE t2 (id INTEGER)")
        applied.append("two")

    runner = MigrationRunner(conn, [up_one, up_two], namespace="store")
    runner.run_pending()

    assert applied == ["one", "two"]
    assert _table_exists(conn, "t1")
    assert _table_exists(conn, "t2")
    assert runner._current_version() == 2


def test_run_pending_applies_migration_dataclass_entries() -> None:
    """Explicit :class:`Migration` entries (with up/down) are applied via ``up``."""
    conn = _make_conn()

    def up(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE widgets (id INTEGER)")

    def down(c: sqlite3.Connection) -> None:
        c.execute("DROP TABLE widgets")

    migration = Migration(up=up, down=down, name="create_widgets")
    runner = MigrationRunner(conn, [migration], namespace="store")
    runner.run_pending()

    assert _table_exists(conn, "widgets")
    assert runner._current_version() == 1


def test_run_pending_is_idempotent_and_skips_already_applied() -> None:
    """Calling ``run_pending`` twice does not re-run already-applied migrations."""
    conn = _make_conn()
    call_count = {"n": 0}

    def up(c: sqlite3.Connection) -> None:
        call_count["n"] += 1
        c.execute("CREATE TABLE IF NOT EXISTS once (id INTEGER)")

    runner = MigrationRunner(conn, [up], namespace="store")
    runner.run_pending()
    runner.run_pending()

    assert call_count["n"] == 1
    assert runner._current_version() == 1


def test_run_pending_only_applies_newly_added_migrations() -> None:
    """Constructing a new runner with additional migrations only applies the new ones."""
    conn = _make_conn()

    def up_one(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE t1 (id INTEGER)")

    def up_two(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE t2 (id INTEGER)")

    MigrationRunner(conn, [up_one], namespace="store").run_pending()
    runner2 = MigrationRunner(conn, [up_one, up_two], namespace="store")
    runner2.run_pending()

    assert _table_exists(conn, "t1")
    assert _table_exists(conn, "t2")
    assert runner2._current_version() == 2


def test_namespaces_track_versions_independently() -> None:
    """Two runners sharing a connection but using different namespaces track separately."""
    conn = _make_conn()

    def up_a(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE a1 (id INTEGER)")

    def up_b1(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE b1 (id INTEGER)")

    def up_b2(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE b2 (id INTEGER)")

    runner_a = MigrationRunner(conn, [up_a], namespace="store_a")
    runner_b = MigrationRunner(conn, [up_b1, up_b2], namespace="store_b")
    runner_a.run_pending()
    runner_b.run_pending()

    assert runner_a._current_version() == 1
    assert runner_b._current_version() == 2


def test_legacy_single_column_schema_version_is_migrated() -> None:
    """A pre-existing single-column ``schema_version`` table is migrated to (namespace, version)."""
    conn = _make_conn()
    conn.execute("CREATE TABLE schema_version (version INTEGER)")
    conn.execute("INSERT INTO schema_version (version) VALUES (3)")
    conn.commit()

    runner = MigrationRunner(conn, [], namespace="store")
    runner._ensure_version_table()

    cols = {row[1] for row in conn.execute("PRAGMA table_info(schema_version)").fetchall()}
    assert "namespace" in cols
    assert runner._current_version() == 3


def test_legacy_schema_migration_with_zero_version_inserts_nothing() -> None:
    """A legacy table with version 0 (falsy) migrates the shape but records no row."""
    conn = _make_conn()
    conn.execute("CREATE TABLE schema_version (version INTEGER)")
    conn.execute("INSERT INTO schema_version (version) VALUES (0)")
    conn.commit()

    runner = MigrationRunner(conn, [], namespace="store")
    runner._ensure_version_table()

    row = conn.execute(
        "SELECT version FROM schema_version WHERE namespace = ?", ("store",)
    ).fetchone()
    assert row is None
    assert runner._current_version() == 0


def test_legacy_schema_migration_with_empty_table_and_no_row() -> None:
    """A legacy table that exists but has no row at all migrates to version 0."""
    conn = _make_conn()
    conn.execute("CREATE TABLE schema_version (version INTEGER)")
    conn.commit()

    runner = MigrationRunner(conn, [], namespace="store")
    runner._ensure_version_table()

    cols = {row[1] for row in conn.execute("PRAGMA table_info(schema_version)").fetchall()}
    assert "namespace" in cols
    assert runner._current_version() == 0


def test_postgres_engine_uses_percent_s_param_style() -> None:
    """Constructing with engine='postgres' selects the '%s' parameter placeholder."""
    conn = _make_conn()
    runner = MigrationRunner(conn, [], namespace="store", engine="postgres")
    assert runner._param == "%s"


def test_rollback_to_runs_down_migrations_in_reverse_order() -> None:
    """``rollback_to`` runs ``down`` callables from current version down to the target."""
    conn = _make_conn()
    order: list[str] = []

    def up_one(c: sqlite3.Connection) -> None:
        order.append("up1")

    def down_one(c: sqlite3.Connection) -> None:
        order.append("down1")

    def up_two(c: sqlite3.Connection) -> None:
        order.append("up2")

    def down_two(c: sqlite3.Connection) -> None:
        order.append("down2")

    migrations = [
        Migration(up=up_one, down=down_one, name="one"),
        Migration(up=up_two, down=down_two, name="two"),
    ]
    runner = MigrationRunner(conn, migrations, namespace="store")
    runner.run_pending()
    order.clear()

    runner.rollback_to(0)

    assert order == ["down2", "down1"]
    assert runner._current_version() == 0


def test_rollback_to_partial_target_stops_early() -> None:
    """``rollback_to`` with a target above 0 only rolls back the newer migrations."""
    conn = _make_conn()
    order: list[str] = []

    def make_up(label: str) -> Callable[[sqlite3.Connection], None]:
        def up(c: sqlite3.Connection) -> None:
            order.append(f"up-{label}")

        return up

    def make_down(label: str) -> Callable[[sqlite3.Connection], None]:
        def down(c: sqlite3.Connection) -> None:
            order.append(f"down-{label}")

        return down

    migrations = [
        Migration(up=make_up("a"), down=make_down("a"), name="a"),
        Migration(up=make_up("b"), down=make_down("b"), name="b"),
        Migration(up=make_up("c"), down=make_down("c"), name="c"),
    ]
    runner = MigrationRunner(conn, migrations, namespace="store")
    runner.run_pending()
    order.clear()

    runner.rollback_to(1)

    assert order == ["down-c", "down-b"]
    assert runner._current_version() == 1


def test_rollback_to_negative_version_raises_value_error() -> None:
    """Rolling back to a negative target version raises ValueError."""
    conn = _make_conn()
    runner = MigrationRunner(conn, [], namespace="store")
    with pytest.raises(ValueError, match="invalid rollback target"):
        runner.rollback_to(-1)


def test_rollback_to_version_above_current_raises_value_error() -> None:
    """Rolling back to a target version above the current version raises ValueError."""
    conn = _make_conn()

    def up(c: sqlite3.Connection) -> None:
        return None

    runner = MigrationRunner(conn, [up], namespace="store")
    runner.run_pending()
    with pytest.raises(ValueError, match="invalid rollback target"):
        runner.rollback_to(5)


def test_run_down_rolls_back_requested_step_count() -> None:
    """``run_down(steps=1)`` rolls back exactly the most recently applied migration."""
    conn = _make_conn()
    order: list[str] = []

    migrations = [
        Migration(up=lambda c: order.append("up1"), down=lambda c: order.append("down1")),
        Migration(up=lambda c: order.append("up2"), down=lambda c: order.append("down2")),
    ]
    runner = MigrationRunner(conn, migrations, namespace="store")
    runner.run_pending()
    order.clear()

    runner.run_down(steps=1)

    assert order == ["down2"]
    assert runner._current_version() == 1


def test_run_down_default_steps_is_one() -> None:
    """``run_down()`` with no explicit ``steps`` argument defaults to rolling back one step."""
    conn = _make_conn()
    order: list[str] = []

    migrations = [
        Migration(up=lambda c: None, down=lambda c: order.append("down1")),
    ]
    runner = MigrationRunner(conn, migrations, namespace="store")
    runner.run_pending()

    runner.run_down()

    assert order == ["down1"]
    assert runner._current_version() == 0


def test_run_down_negative_steps_raises_value_error() -> None:
    """``run_down`` with a negative ``steps`` value raises ValueError before touching the DB."""
    conn = _make_conn()
    runner = MigrationRunner(conn, [], namespace="store")
    with pytest.raises(ValueError, match="steps must be non-negative"):
        runner.run_down(steps=-1)


def test_run_down_more_steps_than_current_raises_value_error() -> None:
    """``run_down`` requesting more steps than have been applied raises ValueError."""
    conn = _make_conn()

    def up(c: sqlite3.Connection) -> None:
        return None

    runner = MigrationRunner(conn, [up], namespace="store")
    runner.run_pending()
    with pytest.raises(ValueError, match="invalid rollback target"):
        runner.run_down(steps=5)


def test_no_op_down_default_is_used_for_bare_callables() -> None:
    """A bare-callable migration (no explicit ``down``) rolls back as a silent no-op."""
    conn = _make_conn()

    def up(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE survivor (id INTEGER)")

    runner = MigrationRunner(conn, [up], namespace="store")
    runner.run_pending()

    runner.rollback_to(0)

    # The no-op down does not undo the DDL; only the recorded version changes.
    assert _table_exists(conn, "survivor")
    assert runner._current_version() == 0
