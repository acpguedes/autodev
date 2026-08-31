"""Tests for process-wide persistence store lifecycle."""

from __future__ import annotations

import pytest

from backend.config.settings import reset_settings_cache
from backend.persistence.database import get_store, reset_store_cache
from backend.persistence.postgres_adapter import PostgresStore
from backend.tests.unit.persistence.fake_postgres_pool import (
    FakeConnectionPool,
    install_fake_postgres_modules,
)
from backend.tests.unit.persistence.test_postgres_adapter import ScriptedConnection


@pytest.fixture(autouse=True)
def clean_store_cache() -> None:
    """Reset the process store cache around each test."""
    reset_settings_cache()
    reset_store_cache()
    yield
    reset_store_cache()
    reset_settings_cache()


def test_reset_store_cache_closes_postgres_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Discarding the cached PostgreSQL store gracefully closes its pool."""
    install_fake_postgres_modules(monkeypatch, connection_factory=ScriptedConnection)
    monkeypatch.setattr(PostgresStore, "_run_migrations", lambda self, conn: None)
    monkeypatch.setattr(
        "backend.persistence.postgres_adapter.store.provision_vector_extension",
        lambda conn: None,
    )
    monkeypatch.setenv("AUTODEV_PROFILE", "prod")
    monkeypatch.setenv("DATABASE_URL", "postgresql://svc:db-secret@postgres/db")
    monkeypatch.setenv("AUTODEV_JOB_BACKEND", "redis")
    monkeypatch.setenv("AUTODEV_EVENT_BUS", "redis")
    monkeypatch.setenv("AUTODEV_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("AUTODEV_MINIO_ENDPOINT", "minio:9000")
    monkeypatch.setenv("AUTODEV_MINIO_ACCESS_KEY", "svc-access-key")
    monkeypatch.setenv("AUTODEV_MINIO_SECRET_KEY", "svc-secret-key")

    get_store()
    pool = FakeConnectionPool.instances[-1]

    reset_store_cache()

    assert pool.closed is True
    assert pool.conn.closed is True
