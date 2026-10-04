"""PostgreSQL-only E62 proofs: migration backfill, project-scoped retrieval, RLS on ``projects``.

Skipped (named) without ``AUTODEV_TEST_POSTGRES_URL``; fails instead on CI's
PostgreSQL leg, like every other case in this suite (E57-S2-T2).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest

from backend.persistence.migrations import MigrationRunner
from backend.persistence.migrations.postgres_versions import POSTGRES_STORE_MIGRATIONS
from backend.persistence.postgres_adapter import PostgresStore
from backend.persistence.tenancy import set_postgres_tenant
from backend.projects import ProjectStore
from backend.repository import indexing
from backend.repository.embeddings.pgvector_store import upsert_embeddings
from backend.repository.embeddings.provider import StubEmbeddingProvider
from backend.repository.retrieval.retriever import RetrievalFilters, retrieve
from backend.tests.persistence_contract.backends import (
    POSTGRES_SKIP_REASON,
    REQUIRE_POSTGRES_ENV,
    drop_postgres_database,
    postgres_admin_url,
    provision_postgres_database,
)


@pytest.fixture()
def pg_url() -> Iterator[str]:
    admin = postgres_admin_url()
    if admin is None:
        if os.environ.get(REQUIRE_POSTGRES_ENV):
            pytest.fail(POSTGRES_SKIP_REASON, pytrace=False)
        pytest.skip(POSTGRES_SKIP_REASON)
    url = provision_postgres_database(admin)
    try:
        yield url
    finally:
        drop_postgres_database(admin, url)


def test_backfill_attaches_sessions_and_chunks_to_default_project(pg_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import psycopg

    monkeypatch.setenv("AUTODEV_PROJECT_ROOT", str(tmp_path))
    with psycopg.connect(pg_url) as conn:
        MigrationRunner(conn, POSTGRES_STORE_MIGRATIONS[:-2], namespace="store", engine="postgres").run_pending()
        conn.commit()
        for tenant in ("t1", "t2"):
            set_postgres_tenant(conn, tenant)
            conn.execute(
                "INSERT INTO sessions (id, goal, plan_json, artifacts_json, tenant_id) VALUES (%s, 'g', '[]', '{}', %s)",
                (f"s-{tenant}", tenant),
            )
            conn.execute(
                "INSERT INTO code_chunks (tenant_id, file_path, symbol, start_line, end_line, content_hash, content) "
                "VALUES (%s, 'x.py', 'f', 0, 1, 'h', 'c')",
                (tenant,),
            )
            conn.commit()
        MigrationRunner(conn, POSTGRES_STORE_MIGRATIONS, namespace="store", engine="postgres").run_pending()
        conn.commit()
        for tenant in ("t1", "t2"):
            set_postgres_tenant(conn, tenant)
            assert conn.execute("SELECT project_id FROM sessions").fetchall() == [("default",)]
            assert conn.execute("SELECT project_id FROM code_chunks").fetchall() == [("default",)]
            assert conn.execute("SELECT project_id, is_active FROM projects").fetchall() == [("default", True)]
            conn.commit()


def test_projects_rls_hides_other_tenants_even_without_a_filter(pg_url: str, tmp_path: Path) -> None:
    store = PostgresStore(pg_url)
    projects = ProjectStore(store=store)
    projects.create(tenant_id="ta", name="a", root_path=tmp_path / "a")
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0  # no tenant GUC -> zero rows (forced RLS)
        set_postgres_tenant(conn, "tb")
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
        set_postgres_tenant(conn, "ta")
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


def test_retrieval_never_returns_another_projects_chunk(pg_url: str, tmp_path: Path) -> None:
    store = PostgresStore(pg_url)
    for name, body in (("ra", "def alpha_only():\n    return 'needle'\n"), ("rb", "def beta_only():\n    return 'needle'\n")):
        root = tmp_path / name
        root.mkdir()
        (root / "same.py").write_text(body, encoding="utf-8")
        indexing.index(root, tenant_id="t", store=store, project_id=f"p-{name}")

    provider = StubEmbeddingProvider()
    with store.connect() as conn:
        set_postgres_tenant(conn, "t")
        rows = conn.execute("SELECT id, content, content_hash FROM code_chunks").fetchall()
        assert len(rows) >= 2  # same relative path coexists in two projects
        upsert_embeddings(conn, [(r[0], r[1], r[2]) for r in rows], provider, tenant_id="t")
        for mode in ("lexical", "vector", "hybrid"):
            for mine, other in (("p-ra", "beta_only"), ("p-rb", "alpha_only")):
                set_postgres_tenant(conn, "t")  # upsert_embeddings committed; the GUC is transaction-local
                snippets = retrieve(
                    conn, "needle", tenant_id="t", mode=mode, embedding_provider=provider,  # type: ignore[arg-type]
                    filters=RetrievalFilters(project_id=mine),
                )
                assert snippets, (mode, mine)
                assert all(s.symbol != other for s in snippets), (mode, mine, [s.symbol for s in snippets])
