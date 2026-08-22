"""Tests for backend/persistence/contract.py (E49-S1/S2)."""

from __future__ import annotations

import sqlite3

import pytest

from backend.persistence.contract import (
    PersistenceIntegrityError,
    begin_write,
    for_update_clause,
    get_connection,
    is_postgres,
    json_column_type,
    jsonb_cast,
    placeholder,
    sql,
    timestamp_column_type,
    translate_integrity_error,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("postgresql://autodev:pw@postgres/autodev", True),
        ("postgres://autodev:pw@postgres/autodev", True),
        ("sqlite:///./autodev.db", False),
        ("sqlite://", False),
        ("", False),
    ],
)
def test_is_postgres(url: str, expected: bool) -> None:
    assert is_postgres(url) is expected


def test_placeholder() -> None:
    assert placeholder(True) == "%s"
    assert placeholder(False) == "?"


def test_jsonb_cast() -> None:
    assert jsonb_cast(True) == "::jsonb"
    assert jsonb_cast(False) == ""


def test_sql_substitutes_placeholder_and_jsonb_cast() -> None:
    template = "INSERT INTO t (a, b) VALUES ({p}, {p}{jsonb})"
    assert sql(template, True) == "INSERT INTO t (a, b) VALUES (%s, %s::jsonb)"
    assert sql(template, False) == "INSERT INTO t (a, b) VALUES (?, ?)"


def test_sql_template_may_omit_either_token() -> None:
    assert sql("SELECT 1", True) == "SELECT 1"
    assert sql("WHERE id = {p}", False) == "WHERE id = ?"


def test_column_type_helpers() -> None:
    assert json_column_type(True) == "JSONB"
    assert json_column_type(False) == "TEXT"
    assert timestamp_column_type(True) == "TIMESTAMPTZ"
    assert timestamp_column_type(False) == "TEXT"


class _RecordingConn:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, statement: str) -> None:
        self.executed.append(statement)


def test_begin_write_issues_begin_immediate_on_sqlite() -> None:
    conn = _RecordingConn()
    begin_write(conn, False)
    assert conn.executed == ["BEGIN IMMEDIATE"]


def test_begin_write_is_a_noop_on_postgres() -> None:
    conn = _RecordingConn()
    begin_write(conn, True)
    assert conn.executed == []


def test_for_update_clause() -> None:
    assert for_update_clause(True) == " FOR UPDATE"
    assert for_update_clause(False) == ""


def test_translate_integrity_error_preserves_message_and_cause() -> None:
    original = sqlite3.IntegrityError("UNIQUE constraint failed: t.id")

    translated = translate_integrity_error(original)

    assert isinstance(translated, PersistenceIntegrityError)
    assert str(translated) == "UNIQUE constraint failed: t.id"
    assert translated.__cause__ is original


def test_get_connection_uses_given_store() -> None:
    class _FakeStore:
        def connect(self) -> str:
            return "connection-from-given-store"

    assert get_connection(_FakeStore()) == "connection-from-given-store"


def test_get_connection_falls_back_to_configured_store(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeStore:
        def connect(self) -> str:
            return "connection-from-configured-store"

    monkeypatch.setattr(
        "backend.persistence.database.get_store", lambda: _FakeStore()
    )

    assert get_connection() == "connection-from-configured-store"
