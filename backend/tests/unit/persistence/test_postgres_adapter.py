"""Unit tests for backend/persistence/postgres_adapter.py (E12-S1).

Covers ``PostgresStore`` and ``PostgresPlanStore``'s CRUD methods using a
scripted fake ``psycopg`` module: a single shared :class:`ScriptedConnection`
(psycopg.connect always returns the same instance, mirroring how the code
under test opens a fresh "connection" per method call while nested calls
like ``list_runs`` -> ``list_run_steps`` and ``append_messages`` ->
``list_messages`` must still observe results in call order) with FIFO
``fetchone``/``fetchall`` queues so exact row values can be scripted per
test.

Migration application (``_run_migrations``) is monkeypatched to a no-op for
every store constructed here: that code path is already covered by the
existing ``backend/tests/test_postgres_store.py`` (untouched by this file),
and the ``POSTGRES_STORE_MIGRATIONS``/``add_tenant_id_and_rls_to_plan_tables``
internals are not needed to exercise the CRUD methods under test — stubbing
them out also avoids those migrations unpredictably consuming the scripted
fetch queues meant for CRUD assertions.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from backend.persistence import postgres_adapter
from backend.persistence.postgres_adapter import PostgresPlanStore, PostgresStore
from backend.plans.models import ApprovalRecord, PlanDocument, PlanStatus


class ScriptedCursor:
    """A cursor-like object backed by its parent connection's scripted state."""

    def __init__(self, conn: "ScriptedConnection") -> None:
        """Bind this cursor to its owning :class:`ScriptedConnection`."""
        self.conn = conn

    def __enter__(self) -> "ScriptedCursor":
        """Support ``with conn.cursor() as cur:`` usage."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """No-op cleanup; nothing to release."""
        return None

    def execute(self, sql: str, params: Any = None) -> "ScriptedCursor":
        """Record the executed statement and return self for chaining."""
        self.conn.executed.append((sql, params))
        return self

    def fetchone(self) -> Any:
        """Pop and return the next scripted single-row result, or ``None``."""
        if self.conn.fetchone_queue:
            return self.conn.fetchone_queue.pop(0)
        return None

    def fetchall(self) -> list[Any]:
        """Pop and return the next scripted multi-row result, or ``[]``."""
        if self.conn.fetchall_queue:
            return self.conn.fetchall_queue.pop(0)
        return []


class ScriptedConnection:
    """A psycopg-connection fake with FIFO fetch queues shared across "connections".

    ``psycopg.connect()`` is monkeypatched to always return the *same*
    instance of this class, because the code under test treats every
    ``self.connect()`` call as opening a fresh connection while nested calls
    (e.g. ``list_runs`` calling ``list_run_steps`` per row) need their queued
    fetch results consumed in the correct overall order.
    """

    def __init__(self) -> None:
        """Initialize empty executed-statement log and fetch queues."""
        self.executed: list[tuple[str, Any]] = []
        self.commits = 0
        self.fetchone_queue: list[Any] = []
        self.fetchall_queue: list[list[Any]] = []

    def __enter__(self) -> "ScriptedConnection":
        """Support ``with self.connect() as conn:`` usage."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """No-op cleanup; nothing to release."""
        return None

    def cursor(self) -> ScriptedCursor:
        """Return a new cursor bound to this connection's scripted state."""
        return ScriptedCursor(self)

    def execute(self, sql: str, params: Any = None) -> ScriptedCursor:
        """Execute directly on the connection (as the code under test does)."""
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def commit(self) -> None:
        """Record that a commit occurred."""
        self.commits += 1


def install_scripted_psycopg(monkeypatch: pytest.MonkeyPatch) -> ScriptedConnection:
    """Install a fake ``psycopg`` module whose ``connect()`` returns a shared connection.

    Args:
        monkeypatch: The active pytest monkeypatch fixture.

    Returns:
        The single :class:`ScriptedConnection` instance every ``connect()``
        call will return.
    """
    conn = ScriptedConnection()

    def connect(database_url: str) -> ScriptedConnection:
        assert database_url.startswith("postgresql://")
        return conn

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    return conn


@pytest.fixture
def scripted_conn(monkeypatch: pytest.MonkeyPatch) -> ScriptedConnection:
    """Install the scripted psycopg fake and return its shared connection."""
    return install_scripted_psycopg(monkeypatch)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, scripted_conn: ScriptedConnection) -> PostgresStore:
    """Build a ``PostgresStore`` against the scripted connection, skipping migrations."""
    monkeypatch.setattr(PostgresStore, "_run_migrations", lambda self, conn: None)
    return PostgresStore(database_url="postgresql://test/db")


@pytest.fixture
def plan_store(monkeypatch: pytest.MonkeyPatch, scripted_conn: ScriptedConnection) -> PostgresPlanStore:
    """Build a ``PostgresPlanStore`` against the scripted connection, skipping migrations."""
    monkeypatch.setattr(PostgresPlanStore, "_run_migrations", lambda self, conn: None)
    return PostgresPlanStore(database_url="postgresql://test/db")


# ---------------------------------------------------------------------------
# PostgresStore: sessions
# ---------------------------------------------------------------------------


def test_create_session_inserts_expected_row(store: PostgresStore, scripted_conn: ScriptedConnection) -> None:
    """create_session issues a parameterized INSERT with JSON-encoded plan/artifacts."""
    store.create_session(
        session_id="s1", goal="build it", plan=["a", "b"], artifacts={"k": "v"}, tenant_id="t1"
    )
    sql, params = scripted_conn.executed[-1]
    assert "INSERT INTO sessions" in sql
    assert params == ("s1", "build it", json.dumps(["a", "b"]), json.dumps({"k": "v"}), "t1")
    assert scripted_conn.commits == 1


def test_get_session_returns_none_when_missing(store: PostgresStore, scripted_conn: ScriptedConnection) -> None:
    """get_session returns None when the scripted fetchone yields no row."""
    scripted_conn.fetchone_queue.append(None)
    assert store.get_session("missing") is None


def test_get_session_maps_row_to_dict(store: PostgresStore, scripted_conn: ScriptedConnection) -> None:
    """get_session maps a found row into the expected dict shape."""
    scripted_conn.fetchone_queue.append(
        ("s1", "goal text", json.dumps(["x"]), json.dumps({"a": 1}), "2024-01-01", "2024-01-02")
    )
    result = store.get_session("s1")
    assert result == {
        "id": "s1",
        "goal": "goal text",
        "plan": ["x"],
        "artifacts": {"a": 1},
        "created_at": "2024-01-01",
        "updated_at": "2024-01-02",
    }


def test_list_sessions_maps_all_rows(store: PostgresStore, scripted_conn: ScriptedConnection) -> None:
    """list_sessions maps every scripted row into the expected dict shape."""
    scripted_conn.fetchall_queue.append(
        [
            ("s1", "goal1", "[]", "{}", "2024-01-01", "2024-01-01"),
            ("s2", "goal2", "[]", "{}", "2024-01-02", "2024-01-02"),
        ]
    )
    result = store.list_sessions()
    assert [row["id"] for row in result] == ["s1", "s2"]
    assert result[0]["plan"] == []
    assert result[0]["artifacts"] == {}


def test_update_session_artifacts_issues_update(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """update_session_artifacts issues an UPDATE with JSON-encoded artifacts."""
    store.update_session_artifacts("s1", {"new": True})
    sql, params = scripted_conn.executed[-1]
    assert "UPDATE sessions SET artifacts_json" in sql
    assert params == (json.dumps({"new": True}), "s1")
    assert scripted_conn.commits == 1


# ---------------------------------------------------------------------------
# PostgresStore: runs and run_steps
# ---------------------------------------------------------------------------


def test_create_run_inserts_run_and_replaces_steps(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """create_run inserts the run row, deletes existing steps, and re-inserts each."""
    store.create_run(
        run_id="r1",
        session_id="s1",
        status="running",
        run_type="auto",
        current_state="planning",
        trigger_message="go",
        results=[],
        steps=[
            {"step_key": "k1", "agent": "a1", "status": "done", "started_at": "t0", "completed_at": "t1", "attempt": 2},
            {"step_key": "k2", "agent": "a2", "status": "pending", "started_at": "t2", "completed_at": None},
        ],
    )
    sqls = [sql for sql, _ in scripted_conn.executed]
    assert any("INSERT INTO runs" in sql for sql in sqls)
    assert any("DELETE FROM run_steps" in sql for sql in sqls)
    insert_step_calls = [(sql, params) for sql, params in scripted_conn.executed if "INSERT INTO run_steps" in sql]
    assert len(insert_step_calls) == 2
    assert insert_step_calls[0][1] == ("r1", "k1", "a1", "done", "t0", "t1", 2)
    # Second step omits "attempt"; defaults to 1.
    assert insert_step_calls[1][1] == ("r1", "k2", "a2", "pending", "t2", None, 1)
    assert scripted_conn.commits == 1


def test_update_run_issues_update_and_replaces_steps(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """update_run issues an UPDATE and re-runs the delete/insert step replacement."""
    store.update_run(
        run_id="r1",
        status="completed",
        current_state="done",
        results=[{"ok": True}],
        steps=[],
    )
    sqls = [sql for sql, _ in scripted_conn.executed]
    assert any("UPDATE runs" in sql for sql in sqls)
    assert any("DELETE FROM run_steps" in sql for sql in sqls)
    assert not any("INSERT INTO run_steps" in sql for sql in sqls)


def test_list_runs_maps_rows_and_nests_steps(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """list_runs maps run rows and nests each run's steps via list_run_steps."""
    scripted_conn.fetchall_queue.append(
        [("r1", "s1", "running", "auto", "planning", "go", "[]", "2024-01-01", "2024-01-02")]
    )
    scripted_conn.fetchall_queue.append([("k1", "a1", "done", "t0", "t1", 1)])

    result = store.list_runs("s1")

    assert len(result) == 1
    assert result[0]["id"] == "r1"
    assert result[0]["completed_at"] == "2024-01-02"
    assert result[0]["steps"] == [
        {"step_key": "k1", "agent": "a1", "status": "done", "started_at": "t0", "completed_at": "t1", "attempt": 1}
    ]


def test_list_runs_completed_at_none_becomes_literal_string(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """A None completed_at is mapped via str(None), yielding the literal string 'None'."""
    scripted_conn.fetchall_queue.append(
        [("r1", "s1", "running", "auto", "planning", "go", "[]", "2024-01-01", None)]
    )
    scripted_conn.fetchall_queue.append([])  # nested list_run_steps call for r1

    result = store.list_runs("s1")

    assert result[0]["completed_at"] == "None"


def test_list_run_steps_direct(store: PostgresStore, scripted_conn: ScriptedConnection) -> None:
    """list_run_steps maps its row tuple directly when called standalone."""
    scripted_conn.fetchall_queue.append([("k1", "a1", "done", "t0", "t1", 3)])
    result = store.list_run_steps("r1")
    assert result == [
        {"step_key": "k1", "agent": "a1", "status": "done", "started_at": "t0", "completed_at": "t1", "attempt": 3}
    ]


# ---------------------------------------------------------------------------
# PostgresStore: messages
# ---------------------------------------------------------------------------


def test_list_messages_maps_rows(store: PostgresStore, scripted_conn: ScriptedConnection) -> None:
    """list_messages maps each row into the expected dict shape."""
    scripted_conn.fetchall_queue.append(
        [("m1", "s1", "r1", 0, "user", "hi", "2024-01-01")]
    )
    result = store.list_messages("s1")
    assert result == [
        {
            "id": "m1",
            "session_id": "s1",
            "run_id": "r1",
            "sequence": 0,
            "role": "user",
            "content": "hi",
            "created_at": "2024-01-01",
        }
    ]


def test_append_messages_no_op_when_nothing_new(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """append_messages short-circuits (no connection/insert) when history has no new items."""
    scripted_conn.fetchall_queue.append(
        [
            ("m1", "s1", "r1", 0, "user", "hi", "2024-01-01"),
            ("m2", "s1", "r1", 1, "assistant", "hello", "2024-01-01"),
        ]
    )
    before_commits = scripted_conn.commits

    store.append_messages("s1", "r1", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}])

    # list_messages() still runs its SELECT to check existing history, but no
    # INSERT/commit happens since there is nothing new to append.
    assert scripted_conn.commits == before_commits
    assert not any("INSERT INTO messages" in sql for sql, _ in scripted_conn.executed)


def test_append_messages_inserts_only_new_items_with_continued_sequence(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """append_messages inserts only the tail of history beyond what already exists."""
    scripted_conn.fetchall_queue.append([("m1", "s1", "r1", 0, "user", "hi", "2024-01-01")])

    store.append_messages(
        "s1",
        "r1",
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ],
    )

    inserts = [(sql, params) for sql, params in scripted_conn.executed if "INSERT INTO messages" in sql]
    assert len(inserts) == 2
    assert inserts[0][1] == ("s1", "r1", 1, "assistant", "second", "default")
    assert inserts[1][1] == ("s1", "r1", 2, "user", "third", "default")
    assert scripted_conn.commits == 1


# ---------------------------------------------------------------------------
# PostgresStore: eval results
# ---------------------------------------------------------------------------


def test_create_eval_result_defaults_gate_passed_true(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """create_eval_result defaults gate_passed to True when no gate.passed is present."""
    store.create_eval_result(eval_id="e1", eval_version="v1", run_id="r1", document={})
    sql, params = scripted_conn.executed[-1]
    assert "INSERT INTO eval_results" in sql
    assert params[4] is True


def test_create_eval_result_explicit_gate_failed(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """create_eval_result honors an explicit gate.passed=False."""
    store.create_eval_result(
        eval_id="e1", eval_version="v1", run_id="r1", document={"gate": {"passed": False}, "mode": "online"}
    )
    sql, params = scripted_conn.executed[-1]
    assert params[4] is False
    assert params[3] == "online"


def test_get_eval_result_none_and_found(store: PostgresStore, scripted_conn: ScriptedConnection) -> None:
    """get_eval_result returns None when missing, and the decoded document when found."""
    scripted_conn.fetchone_queue.append(None)
    assert store.get_eval_result("e1", "v1", "r1") is None

    scripted_conn.fetchone_queue.append((json.dumps({"score": 1}),))
    assert store.get_eval_result("e1", "v1", "r1") == {"score": 1}


def test_list_eval_results_with_version_uses_versioned_sql(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """list_eval_results filters by eval_version when one is provided."""
    scripted_conn.fetchall_queue.append([(json.dumps({"a": 1}),)])
    result = store.list_eval_results("e1", eval_version="v1")
    sql, params = scripted_conn.executed[-1]
    assert "eval_version = %s" in sql
    assert params == ("e1", "v1")
    assert result == [{"a": 1}]


def test_list_eval_results_without_version_omits_version_filter(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """list_eval_results omits the version filter when eval_version is None."""
    scripted_conn.fetchall_queue.append([])
    store.list_eval_results("e1")
    sql, params = scripted_conn.executed[-1]
    assert "eval_version" not in sql
    assert params == ("e1",)


# ---------------------------------------------------------------------------
# PostgresStore: score snapshots
# ---------------------------------------------------------------------------


def test_create_score_snapshot_inserts_row(store: PostgresStore, scripted_conn: ScriptedConnection) -> None:
    """create_score_snapshot issues a parameterized INSERT."""
    store.create_score_snapshot(snapshot_id="ss1", sample_count=10, document={"m": 1})
    sql, params = scripted_conn.executed[-1]
    assert "INSERT INTO score_snapshots" in sql
    assert params == ("ss1", 10, json.dumps({"m": 1}), "default")


def test_get_score_snapshot_none_and_found(store: PostgresStore, scripted_conn: ScriptedConnection) -> None:
    """get_score_snapshot returns None when missing, and the document when found."""
    scripted_conn.fetchone_queue.append(None)
    assert store.get_score_snapshot("ss1") is None

    scripted_conn.fetchone_queue.append((json.dumps({"m": 1}),))
    assert store.get_score_snapshot("ss1") == {"m": 1}


def test_list_score_snapshots_uses_limit_param(store: PostgresStore, scripted_conn: ScriptedConnection) -> None:
    """list_score_snapshots passes the limit through as a query parameter."""
    scripted_conn.fetchall_queue.append([(json.dumps({"m": 1}),)])
    result = store.list_score_snapshots(limit=5)
    sql, params = scripted_conn.executed[-1]
    assert "LIMIT %s" in sql
    assert params == (5,)
    assert result == [{"m": 1}]


def test_record_snapshot_promotion_inserts_row(store: PostgresStore, scripted_conn: ScriptedConnection) -> None:
    """record_snapshot_promotion issues a parameterized INSERT with all fields."""
    store.record_snapshot_promotion(
        policy_id="p1",
        snapshot_id="ss1",
        baseline_snapshot_id="ss0",
        promoted=True,
        reason="better",
        decided_at="2024-01-01",
    )
    sql, params = scripted_conn.executed[-1]
    assert "INSERT INTO score_snapshot_promotions" in sql
    assert params == ("p1", "ss1", "ss0", True, "better", "2024-01-01")


def test_get_active_score_snapshot_returns_none_when_no_promotion(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """get_active_score_snapshot returns None when no promoted row exists."""
    scripted_conn.fetchone_queue.append(None)
    assert store.get_active_score_snapshot("p1") is None


def test_get_active_score_snapshot_resolves_nested_snapshot(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """get_active_score_snapshot follows the promoted snapshot_id to fetch its document."""
    scripted_conn.fetchone_queue.append(("ss1",))
    scripted_conn.fetchone_queue.append((json.dumps({"m": 42}),))
    result = store.get_active_score_snapshot("p1")
    assert result == {"m": 42}


def test_list_snapshot_promotions_maps_camel_case_keys(
    store: PostgresStore, scripted_conn: ScriptedConnection
) -> None:
    """list_snapshot_promotions maps rows into camelCase dict keys with promoted as bool."""
    scripted_conn.fetchall_queue.append([("p1", "ss1", "ss0", 1, "why", "2024-01-01")])
    result = store.list_snapshot_promotions("p1")
    assert result == [
        {
            "policyId": "p1",
            "snapshotId": "ss1",
            "baselineSnapshotId": "ss0",
            "promoted": True,
            "reason": "why",
            "decidedAt": "2024-01-01",
        }
    ]


# ---------------------------------------------------------------------------
# PostgresPlanStore
# ---------------------------------------------------------------------------


def test_upsert_plan_inserts_with_draft_status(
    plan_store: PostgresPlanStore, scripted_conn: ScriptedConnection
) -> None:
    """upsert_plan issues an upsert with the steps JSON-encoded and status hardcoded to draft."""
    plan_store.upsert_plan("s1", ["step1", "step2"])
    sql, params = scripted_conn.executed[-1]
    assert "INSERT INTO plan_documents" in sql
    assert params[0] == "s1"
    assert params[1] == json.dumps(["step1", "step2"])
    assert params[3] == "default"
    assert scripted_conn.commits == 1


def test_get_plan_none_and_found(plan_store: PostgresPlanStore, scripted_conn: ScriptedConnection) -> None:
    """get_plan returns None when missing, and a PlanDocument when found."""
    scripted_conn.fetchone_queue.append(None)
    assert plan_store.get_plan("s1") is None

    scripted_conn.fetchone_queue.append(("s1", json.dumps(["a"]), "draft", "2024-01-01"))
    result = plan_store.get_plan("s1")
    assert result == PlanDocument(session_id="s1", steps=["a"], status="draft", updated_at="2024-01-01")


def test_set_status_issues_update(plan_store: PostgresPlanStore, scripted_conn: ScriptedConnection) -> None:
    """set_status issues an UPDATE with the new status and a timestamp."""
    plan_store.set_status("s1", PlanStatus.APPROVED)
    sql, params = scripted_conn.executed[-1]
    assert "UPDATE plan_documents SET status" in sql
    assert params[0] == "approved"
    assert params[2] == "s1"


def test_approve_updates_status_and_appends_approval(
    plan_store: PostgresPlanStore, scripted_conn: ScriptedConnection
) -> None:
    """approve() sets status to approved and records an approval decision."""
    plan_store.approve("s1", actor="alice", note="lgtm")

    updates = [(sql, params) for sql, params in scripted_conn.executed if "UPDATE plan_documents" in sql]
    inserts = [(sql, params) for sql, params in scripted_conn.executed if "INSERT INTO plan_approvals" in sql]
    assert updates[-1][1][0] == "approved"
    assert inserts[-1][1] == ("s1", "approved", "alice", "lgtm", inserts[-1][1][4], "default")


def test_reject_updates_status_and_appends_rejection(
    plan_store: PostgresPlanStore, scripted_conn: ScriptedConnection
) -> None:
    """reject() sets status to rejected and records a rejection decision."""
    plan_store.reject("s1", actor="bob", note="needs work")

    updates = [(sql, params) for sql, params in scripted_conn.executed if "UPDATE plan_documents" in sql]
    inserts = [(sql, params) for sql, params in scripted_conn.executed if "INSERT INTO plan_approvals" in sql]
    assert updates[-1][1][0] == "rejected"
    assert inserts[-1][1][1] == "rejected"
    assert inserts[-1][1][2] == "bob"


def test_list_plans_maps_rows(plan_store: PostgresPlanStore, scripted_conn: ScriptedConnection) -> None:
    """list_plans maps every row into a PlanDocument."""
    scripted_conn.fetchall_queue.append(
        [("s1", json.dumps(["a"]), "draft", "2024-01-01"), ("s2", json.dumps([]), "approved", "2024-01-02")]
    )
    result = plan_store.list_plans()
    assert result == [
        PlanDocument(session_id="s1", steps=["a"], status="draft", updated_at="2024-01-01"),
        PlanDocument(session_id="s2", steps=[], status="approved", updated_at="2024-01-02"),
    ]


def test_list_approvals_maps_rows(plan_store: PostgresPlanStore, scripted_conn: ScriptedConnection) -> None:
    """list_approvals maps every row into an ApprovalRecord."""
    scripted_conn.fetchall_queue.append([("s1", "approved", "alice", "lgtm", "2024-01-01")])
    result = plan_store.list_approvals("s1")
    assert result == [
        ApprovalRecord(session_id="s1", decision="approved", actor="alice", note="lgtm", created_at="2024-01-01")
    ]


def test_database_url_fallback_chain(
    monkeypatch: pytest.MonkeyPatch, scripted_conn: ScriptedConnection
) -> None:
    """database_url resolves: explicit param > DATABASE_URL env var > module default."""
    monkeypatch.setattr(PostgresPlanStore, "_run_migrations", lambda self, conn: None)

    monkeypatch.setenv("DATABASE_URL", "postgresql://from-env/db")
    explicit = PostgresPlanStore(database_url="postgresql://explicit/db")
    assert explicit.database_url == "postgresql://explicit/db"

    from_env = PostgresPlanStore()
    assert from_env.database_url == "postgresql://from-env/db"

    monkeypatch.delenv("DATABASE_URL", raising=False)
    default = PostgresPlanStore()
    assert default.database_url == postgres_adapter._DEFAULT_DATABASE_URL
