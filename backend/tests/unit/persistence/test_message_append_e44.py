"""Incremental message-append contract tests (E44-S4).

``append_messages`` used to take the full conversation and re-read every
stored message just to compute ``len(existing)``, so the bytes read over a
conversation's life grew quadratically. It now takes only the new tail and
allocates sequence numbers from ``MAX(sequence) + 1`` inside the insert
transaction, guarded by a unique ``(tenant_id, session_id, sequence)`` index.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.persistence.sqlite_adapter import SQLiteStore

from backend.tests.unit.persistence.test_run_lookup_e44 import StatementCounter


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    """Build a :class:`SQLiteStore` with one seeded session."""
    store = SQLiteStore(database_url=f"sqlite:///{tmp_path / 'e44-s4.db'}")
    store.create_session(session_id="s1", goal="g", plan=[], artifacts={})
    return store


def _append(store: SQLiteStore, *contents: str, run_id: str = "r1") -> None:
    """Append one message per entry in *contents*."""
    store.append_messages(
        "s1", run_id, [{"role": "user", "content": content} for content in contents]
    )


def test_sequences_continue_across_appends(store: SQLiteStore) -> None:
    """Successive appends keep numbering from the stored maximum."""
    _append(store, "a", "b")
    _append(store, "c")

    stored = store.list_messages("s1")
    assert [row["content"] for row in stored] == ["a", "b", "c"]
    assert [row["sequence"] for row in stored] == [0, 1, 2]


def test_appending_nothing_is_a_no_op(store: SQLiteStore) -> None:
    """An empty tail writes nothing and opens no connection."""
    _append(store, "a")
    counter = StatementCounter()
    counter.install(store)

    store.append_messages("s1", "r1", [])

    assert counter.connections == 0
    assert len(store.list_messages("s1")) == 1


def test_append_reads_one_row_regardless_of_history_length(store: SQLiteStore) -> None:
    """Appending to a long conversation still costs a single-row read (E44-S4)."""
    _append(store, *[f"m{i}" for i in range(200)])
    counter = StatementCounter()
    counter.install(store)

    _append(store, "tail")

    # One MAX(sequence) probe plus the insert — never a full history re-read.
    assert counter.connections == 1
    assert sum("SELECT" in statement for statement in counter.statements) == 1
    assert store.list_messages("s1")[-1]["sequence"] == 200


def test_sequence_allocation_is_scoped_per_tenant(store: SQLiteStore) -> None:
    """Another tenant's messages never shift this tenant's sequence numbers."""
    store.append_messages(
        "s1",
        "r",
        [{"role": "user", "content": f"other{i}"} for i in range(5)],
        tenant_id="other",
    )

    _append(store, "mine")

    mine = store.list_messages("s1")
    assert [(row["sequence"], row["content"]) for row in mine] == [(0, "mine")]
    theirs = store.list_messages("s1", tenant_id="other")
    assert [row["sequence"] for row in theirs] == [0, 1, 2, 3, 4]


def test_duplicate_sequence_fails_closed(store: SQLiteStore) -> None:
    """The unique index rejects a second row claiming an existing sequence.

    Simulates the interleaving two concurrent appends would produce if both
    read the same ``MAX(sequence)``: the loser must fail rather than silently
    corrupt the conversation's ordering.
    """
    _append(store, "a")

    with store.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO messages (session_id, run_id, sequence, role, content, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("s1", "r1", 0, "user", "duplicate", "default"),
            )

    assert len(store.list_messages("s1")) == 1
