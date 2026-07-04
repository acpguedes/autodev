"""Tests for the PostgreSQL state-store adapter."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from backend.persistence.postgres_adapter import PostgresPlanStore, PostgresStore


class FakeCursor:
    def __init__(self, conn: "FakeConnection") -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> "FakeCursor":
        self.conn.executed.append((sql, params))
        return self

    def fetchone(self) -> object:
        return None

    def fetchall(self) -> list[object]:
        return []


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, object]] = []
        self.commits = 0

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def execute(self, sql: str, params: object = None) -> FakeCursor:
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def commit(self) -> None:
        self.commits += 1


def install_fake_psycopg(monkeypatch) -> list[FakeConnection]:
    connections: list[FakeConnection] = []

    def connect(database_url: str) -> FakeConnection:
        assert database_url.startswith("postgresql://")
        conn = FakeConnection()
        connections.append(conn)
        return conn

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    return connections


def test_postgres_store_runs_core_migrations(monkeypatch) -> None:
    connections = install_fake_psycopg(monkeypatch)

    PostgresStore("postgresql://autodev:autodev@postgres/autodev")

    executed_sql = "\n".join(sql for sql, _params in connections[0].executed)
    assert "CREATE TABLE IF NOT EXISTS sessions" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS runs" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS run_steps" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS messages" in executed_sql


def test_postgres_plan_store_runs_plan_migrations(monkeypatch) -> None:
    connections = install_fake_psycopg(monkeypatch)

    PostgresPlanStore(database_url="postgresql://autodev:autodev@postgres/autodev")

    executed_sql = "\n".join(sql for sql, _params in connections[0].executed)
    assert "CREATE TABLE IF NOT EXISTS plan_documents" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS plan_approvals" in executed_sql
