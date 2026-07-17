"""Tests for the E7-S1 tree-sitter indexing pipeline: parsing, chunking, incremental reindex."""

from __future__ import annotations

import json
import time
from pathlib import Path

from backend.jobs.queue import InProcessJobQueue, RedisJobQueue
from backend.persistence.sqlite_adapter import SQLiteStore
from backend.repository import chunking, indexing
from backend.repository.providers.lexical_provider import LexicalProvider
from backend.repository.providers.treesitter_provider import TreeSitterProvider

_PY_SAMPLE_A = """\
def add(a, b):
    return a + b


class Greeter:
    def greet(self, name):
        return f"hello {name}"


def subtract(a, b):
    return a - b
"""

_PY_SAMPLE_B = """\
import os


def list_files(path):
    return os.listdir(path)
"""


def _make_fixture_repo(tmp_path: Path) -> Path:
    """Build a small 3-file Python fixture repo under *tmp_path* for indexing tests."""
    repo = tmp_path / "fixture_repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod_a.py").write_text(_PY_SAMPLE_A, encoding="utf-8")
    (repo / "pkg" / "mod_b.py").write_text(_PY_SAMPLE_B, encoding="utf-8")
    (repo / "top_level.py").write_text("def top():\n    pass\n", encoding="utf-8")
    return repo


def _make_store(tmp_path: Path) -> SQLiteStore:
    """Build a fresh SQLiteStore backed by a temp file, so migrations create ``code_chunks``."""
    return SQLiteStore(f"sqlite:///{tmp_path / 'index.db'}")


# ---------------------------------------------------------------------------
# Real tree-sitter parsing (E7-S1-T1)
# ---------------------------------------------------------------------------


def test_treesitter_provider_extracts_real_spans_for_fixture() -> None:
    """A real tree-sitter parse of the fixture finds every function/class, with correct spans."""
    provider = TreeSitterProvider()
    spans = provider.extract_symbol_spans(_PY_SAMPLE_A, "python")
    names = {span.name for span in spans}
    assert {"add", "Greeter", "greet", "subtract"} <= names
    add_span = next(span for span in spans if span.name == "add")
    assert add_span.kind == "function"
    assert add_span.start_line == 0
    greeter_span = next(span for span in spans if span.name == "Greeter")
    assert greeter_span.kind == "class"


def test_treesitter_provider_extracts_symbols_including_imports() -> None:
    """extract_symbols() includes both definitions and import names, in source order."""
    provider = TreeSitterProvider()
    symbols = provider.extract_symbols(_PY_SAMPLE_B, "python")
    assert "list_files" in symbols
    assert "os" in symbols


# ---------------------------------------------------------------------------
# Syntax-aware chunking (E7-S1-T2)
# ---------------------------------------------------------------------------


def test_chunk_source_splits_at_symbol_boundaries() -> None:
    """Chunking a multi-symbol file produces one chunk per function/class, each hashed."""
    chunks = chunking.chunk_source("pkg/mod_a.py", _PY_SAMPLE_A, "python", overlap_lines=0)
    symbols = {chunk.symbol for chunk in chunks}
    assert {"add", "Greeter", "greet", "subtract"} <= symbols
    for chunk in chunks:
        assert chunk.content_hash
        assert chunk.file_path == "pkg/mod_a.py"


def test_chunk_source_falls_back_to_whole_file_without_symbols() -> None:
    """A file with no top-level def/class falls back to a single whole-file chunk."""
    chunks = chunking.chunk_source("empty.py", "x = 1\n", "python", provider=LexicalProvider())
    assert len(chunks) == 1
    assert chunks[0].symbol == ""
    assert chunks[0].content == "x = 1\n"


def test_chunk_source_empty_code_returns_no_chunks() -> None:
    """Empty source produces no chunks at all."""
    assert chunking.chunk_source("empty.py", "", "python") == []


# ---------------------------------------------------------------------------
# index() / reindex() pipeline (E7-S1-T3/T4)
# ---------------------------------------------------------------------------


def test_index_persists_chunk_metadata_for_fixture_repo(tmp_path: Path) -> None:
    """Indexing the fixture repo persists file/symbol/span/hash metadata for every file."""
    repo = _make_fixture_repo(tmp_path)
    store = _make_store(tmp_path)

    written = indexing.index(repo, tenant_id="default", store=store)

    assert written > 0
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT file_path, symbol, start_line, end_line, content_hash FROM code_chunks "
            "ORDER BY file_path, start_line"
        ).fetchall()
    file_paths = {row[0] for row in rows}
    assert file_paths == {"pkg/mod_a.py", "pkg/mod_b.py", "top_level.py"}
    symbols_a = {row[1] for row in rows if row[0] == "pkg/mod_a.py"}
    assert {"add", "Greeter", "greet", "subtract"} <= symbols_a
    for row in rows:
        assert row[4]  # content_hash present
        assert row[3] >= row[2]  # end_line >= start_line


def test_reindex_only_rewrites_the_changed_file(tmp_path: Path) -> None:
    """Reindexing one modified file leaves every other file's stored chunks byte-identical."""
    repo = _make_fixture_repo(tmp_path)
    store = _make_store(tmp_path)
    indexing.index(repo, tenant_id="default", store=store)

    with store.connect() as conn:
        before = {
            (row[0], row[1], row[2]): row[3]
            for row in conn.execute(
                "SELECT file_path, symbol, start_line, content_hash FROM code_chunks"
            ).fetchall()
        }

    mod_b = repo / "pkg" / "mod_b.py"
    mod_b.write_text(_PY_SAMPLE_B + "\n\ndef extra():\n    return 1\n", encoding="utf-8")

    written = indexing.reindex([str(mod_b)], repo_root=repo, tenant_id="default", store=store)
    assert written >= 1

    with store.connect() as conn:
        after = {
            (row[0], row[1], row[2]): row[3]
            for row in conn.execute(
                "SELECT file_path, symbol, start_line, content_hash FROM code_chunks"
            ).fetchall()
        }

    for key, content_hash in before.items():
        if key[0] != "pkg/mod_b.py":
            assert after[key] == content_hash, f"untouched file's chunk {key} changed"

    assert any(key[0] == "pkg/mod_b.py" and key[1] == "extra" for key in after)


def test_reindex_is_idempotent_when_nothing_changed(tmp_path: Path) -> None:
    """Reindexing a file with no content changes writes zero rows (pure hash match)."""
    repo = _make_fixture_repo(tmp_path)
    store = _make_store(tmp_path)
    indexing.index(repo, tenant_id="default", store=store)

    mod_a = repo / "pkg" / "mod_a.py"
    written = indexing.reindex([str(mod_a)], repo_root=repo, tenant_id="default", store=store)

    assert written == 0


def test_reindex_deletes_chunks_for_removed_file(tmp_path: Path) -> None:
    """Reindexing a path that no longer exists on disk purges its stored chunks."""
    repo = _make_fixture_repo(tmp_path)
    store = _make_store(tmp_path)
    indexing.index(repo, tenant_id="default", store=store)

    top_level = repo / "top_level.py"
    top_level.unlink()

    indexing.reindex([str(top_level)], repo_root=repo, tenant_id="default", store=store)

    with store.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM code_chunks WHERE file_path = 'top_level.py'"
        ).fetchone()[0]
    assert count == 0


def test_index_scopes_chunks_by_tenant(tmp_path: Path) -> None:
    """Chunks indexed under different tenants do not collide or overwrite each other."""
    repo = _make_fixture_repo(tmp_path)
    store = _make_store(tmp_path)

    indexing.index(repo, tenant_id="tenant-a", store=store)
    indexing.index(repo, tenant_id="tenant-b", store=store)

    with store.connect() as conn:
        counts = conn.execute(
            "SELECT tenant_id, COUNT(*) FROM code_chunks GROUP BY tenant_id"
        ).fetchall()
    tenants = {row[0]: row[1] for row in counts}
    assert tenants["tenant-a"] == tenants["tenant-b"]
    assert tenants["tenant-a"] > 0


# ---------------------------------------------------------------------------
# Incremental reindex job wiring (E7-S1-T3)
# ---------------------------------------------------------------------------


class _FakeRedisClient:
    """Minimal stand-in for a redis-py client, recording hset/rpush calls (no live server)."""

    def __init__(self) -> None:
        self.hset_calls: list[tuple[str, dict]] = []
        self.rpush_calls: list[tuple[str, str]] = []

    def ping(self) -> bool:
        return True

    def hset(self, key: str, mapping: dict) -> None:
        self.hset_calls.append((key, mapping))

    def rpush(self, key: str, value: str) -> None:
        self.rpush_calls.append((key, value))


def test_enqueue_file_changed_calls_redis_queue_enqueue_with_expected_job(monkeypatch) -> None:
    """enqueue_file_changed() drives RedisJobQueue.enqueue with the right job_type/payload."""
    fake_client = _FakeRedisClient()
    redis_queue = RedisJobQueue(client=fake_client, start_worker=False)
    monkeypatch.setattr(indexing, "get_queue", lambda: redis_queue)

    job_id = indexing.enqueue_file_changed("pkg/mod_a.py", repo_root="/repo", tenant_id="acme")

    assert fake_client.rpush_calls == [(RedisJobQueue._pending_key, job_id)]
    assert len(fake_client.hset_calls) == 1
    _key, mapping = fake_client.hset_calls[0]
    assert mapping["job_type"] == "repo.index.reindex_file"
    payload = json.loads(mapping["payload"])
    assert payload == {"path": "pkg/mod_a.py", "repo_root": "/repo", "tenant_id": "acme"}


def test_reindex_file_job_handler_runs_via_inprocess_queue(tmp_path: Path, monkeypatch) -> None:
    """The registered job handler reindexes the target file when run on the default in-process queue."""
    repo = _make_fixture_repo(tmp_path)
    store = _make_store(tmp_path)
    monkeypatch.setattr(indexing, "get_store", lambda: store)

    queue = InProcessJobQueue()
    job_id = queue.enqueue(
        "repo.index.reindex_file",
        {"path": "top_level.py", "repo_root": str(repo), "tenant_id": "default"},
    )

    deadline = time.time() + 5
    record = queue.get(job_id)
    while record["status"] in ("pending", "running") and time.time() < deadline:
        time.sleep(0.05)
        record = queue.get(job_id)

    assert record["status"] == "done", record
    assert record["result"]["chunks_written"] >= 1

    with store.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM code_chunks WHERE file_path = 'top_level.py'"
        ).fetchone()[0]
    assert count >= 1
