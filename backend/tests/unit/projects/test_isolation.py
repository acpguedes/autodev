"""E62-S5: two projects in one tenant are isolated on sessions/memory, repository knowledge and configuration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.config.runtime import RuntimeConfigService
from backend.context.providers.session_memory import SessionMemoryContextProvider
from backend.persistence.migrations import MigrationRunner
from backend.persistence.migrations.runner import Migration
from backend.persistence.migrations.postgres_versions import POSTGRES_STORE_MIGRATIONS
from backend.persistence.migrations.versions import STORE_MIGRATIONS
from backend.persistence.sqlite_adapter import SQLiteStore
from backend.projects import ProjectStore
from backend.repository import indexing
from backend.repository.retrieval import retriever as retriever_module
from backend.repository.retrieval.retriever import RetrievalFilters, retrieve

TENANT = "default"


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(f"sqlite:///{tmp_path / 'iso.db'}")


def _repo(root: Path, body: str) -> Path:
    root.mkdir()
    (root / "same_name.py").write_text(body, encoding="utf-8")
    return root


def test_session_memory_is_isolated_per_project(store: SQLiteStore, tmp_path: Path) -> None:
    projects = ProjectStore(store=store)
    pa = projects.create(tenant_id=TENANT, name="a", root_path=tmp_path / "a")
    pb = projects.create(tenant_id=TENANT, name="b", root_path=tmp_path / "b")
    store.create_session(session_id="sa", goal="g", plan=[], artifacts={}, tenant_id=TENANT, project_id=pa.project_id)
    store.create_session(session_id="sb", goal="g", plan=[], artifacts={}, tenant_id=TENANT, project_id=pb.project_id)
    store.append_messages("sa", "r1", [{"role": "user", "content": "secret of project A"}], tenant_id=TENANT)
    store.append_messages("sb", "r2", [{"role": "user", "content": "secret of project B"}], tenant_id=TENANT)
    memory = SessionMemoryContextProvider(store=store)

    own = memory.get_context("q", session_id="sa", project_id=pa.project_id)
    assert [i.content for i in own] == ["user: secret of project A"]
    # Project B's context can never be handed project A's session, and vice versa.
    assert memory.get_context("q", session_id="sa", project_id=pb.project_id) == []
    assert memory.get_context("q", session_id="sb", project_id=pa.project_id) == []
    assert [i.content for i in memory.get_context("q", session_id="sb", project_id=pb.project_id)] == [
        "user: secret of project B"
    ]


def test_indexing_keeps_same_relative_path_separate_per_project(store: SQLiteStore, tmp_path: Path) -> None:
    repo_a = _repo(tmp_path / "ra", "def only_in_a():\n    return 'A'\n")
    repo_b = _repo(tmp_path / "rb", "def only_in_b():\n    return 'B'\n")
    indexing.index(repo_a, tenant_id=TENANT, store=store, project_id="pa")
    indexing.index(repo_b, tenant_id=TENANT, store=store, project_id="pb")

    def symbols(project: str) -> set[str]:
        with store.connect() as conn:
            rows = conn.execute(
                "SELECT symbol FROM code_chunks WHERE tenant_id = ? AND project_id = ?", (TENANT, project)
            ).fetchall()
        return {r[0] for r in rows}

    assert "only_in_a" in symbols("pa") and "only_in_b" not in symbols("pa")
    assert "only_in_b" in symbols("pb") and "only_in_a" not in symbols("pb")

    # Reindexing / deleting a file in A touches nothing in B.
    (repo_a / "same_name.py").unlink()
    indexing.reindex(["same_name.py"], repo_root=repo_a, tenant_id=TENANT, store=store, project_id="pa")
    assert symbols("pa") == set()
    assert "only_in_b" in symbols("pb")


def test_retrieval_filters_every_stage_by_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """The project scope reaches the lexical ranker, the vector ranker and the final fetch."""
    seen: dict[str, object] = {}

    def fake_lexical(*args, **kwargs):
        seen["lexical"] = kwargs["project_id"]
        return [(1, 1.0)]

    def fake_vector(*args, **kwargs):
        seen["vector"] = kwargs["project_id"]
        return [(1, 0.1)]

    monkeypatch.setattr(retriever_module.lexical, "search", fake_lexical)
    monkeypatch.setattr(retriever_module, "query_top_k", fake_vector)

    def fake_fetch(conn, chunk_ids, tenant_id, filters):
        seen["fetch"] = filters.project_id
        return [{"id": 1, "file_path": "f.py", "symbol": "s", "start_line": 0, "end_line": 1, "content": "c"}]

    monkeypatch.setattr(retriever_module, "_fetch_chunks", fake_fetch)
    retrieve(object(), "q", tenant_id=TENANT, mode="hybrid", filters=RetrievalFilters(project_id="pa"))
    assert seen == {"lexical": "pa", "vector": "pa", "fetch": "pa"}


def test_postgres_sql_carries_the_project_predicate() -> None:
    from backend.repository.embeddings import pgvector_store
    from backend.repository.retrieval import lexical

    captured: list[tuple[str, tuple]] = []

    class _Result:
        def fetchall(self):
            return []

    class _Conn:
        def execute(self, sql, params=()):
            captured.append((" ".join(sql.split()), tuple(params)))
            return _Result()

    lexical.search(_Conn(), "q", tenant_id=TENANT, project_id="pa")
    retriever_module._fetch_chunks(_Conn(), [1], TENANT, RetrievalFilters(project_id="pa"))
    pgvector_store.register_vector_adapter = lambda conn: False  # type: ignore[assignment]
    pgvector_store.query_top_k(_Conn(), [0.0], tenant_id=TENANT, project_id="pa")
    for sql, params in captured:
        assert "project_id = %s" in sql and "pa" in params, sql


def test_code_chunks_migration_backfills_to_default_project_and_widens_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_PROJECT_ROOT", str(tmp_path))
    conn = sqlite3.connect(tmp_path / "legacy.db")
    MigrationRunner(conn, STORE_MIGRATIONS[:-1], namespace="store").run_pending()
    conn.execute(
        "INSERT INTO code_chunks (tenant_id, file_path, symbol, start_line, end_line, content_hash, content) "
        "VALUES ('default', 'x.py', 'f', 0, 1, 'h', 'c')"
    )
    conn.commit()
    MigrationRunner(conn, STORE_MIGRATIONS, namespace="store").run_pending()
    assert conn.execute("SELECT project_id, content FROM code_chunks").fetchall() == [("default", "c")]
    assert conn.execute("SELECT project_id FROM projects WHERE tenant_id = 'default'").fetchall() == [("default",)]
    # The widened key lets another project hold the same (file, symbol, line).
    conn.execute(
        "INSERT INTO code_chunks (tenant_id, project_id, file_path, symbol, start_line, end_line, content_hash) "
        "VALUES ('default', 'other', 'x.py', 'f', 0, 1, 'h')"
    )
    # ... but not the same project twice.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO code_chunks (tenant_id, project_id, file_path, symbol, start_line, end_line, content_hash) "
            "VALUES ('default', 'other', 'x.py', 'f', 0, 1, 'h')"
        )


def test_postgres_code_chunks_migration_widens_key_and_backfills() -> None:
    migration = next(m for m in POSTGRES_STORE_MIGRATIONS if getattr(m, "name", "") == "add_project_id_to_code_chunks")
    assert isinstance(migration, Migration)
    executed: list[str] = []

    class _Conn:
        def execute(self, sql, params=None):
            executed.append(" ".join(str(sql).split()))

    migration.up(_Conn())
    text = "\n".join(executed)
    assert "ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT ''" in text
    assert "UNIQUE (tenant_id, project_id, file_path, symbol, start_line)" in text
    assert text.index("NO FORCE ROW LEVEL SECURITY") < text.index("UPDATE code_chunks") < text.rindex("FORCE ROW LEVEL SECURITY")


def test_project_config_does_not_leak_across_projects(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AUTODEV_CONFIG_PATH", raising=False)
    monkeypatch.delenv("AUTODEV_PROJECT_ROOT", raising=False)
    for var in ("LLM_PROVIDER", "OPENAI_MODEL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    global_cfg = tmp_path / "global.json"
    global_cfg.write_text(json.dumps({"llm": {"provider": "openai", "model": "global-model"}}))
    roots = {}
    for name, model in (("a", "model-a"), ("b", None)):
        root = tmp_path / name
        (root / ".autodev").mkdir(parents=True)
        (root / ".autodev" / "config.json").write_text(json.dumps({"llm": {"model": model}} if model else {}))
        roots[name] = root

    def service(root: Path) -> RuntimeConfigService:
        return RuntimeConfigService(default_project_root=root, global_config_path=global_cfg)

    a, b = service(roots["a"]).load(), service(roots["b"]).load()
    assert a.llm.model == "model-a" and a.llm.provider == "openai"  # override + inherited field
    assert b.llm.model == "global-model"  # A's override did not leak into B
    assert a.repository.project_root == str(roots["a"].resolve())
    assert b.repository.project_root == str(roots["b"].resolve())
    # Saving B writes nothing it merely inherits, and A's file is untouched.
    before = (roots["a"] / ".autodev" / "config.json").read_text()
    svc_b = service(roots["b"])
    svc_b.save(svc_b.load())
    assert (roots["a"] / ".autodev" / "config.json").read_text() == before
    assert service(roots["a"]).load().llm.model == "model-a"
