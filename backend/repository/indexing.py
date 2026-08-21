"""Repository indexing pipeline (E7-S1-T3/T4).

``index(repo_path)`` walks a repository, chunks every source file via
:mod:`backend.repository.chunking`, and persists chunk metadata (file path,
span, symbol, content hash) into the active durable store's ``code_chunks``
table (created by the migrations in
``backend/persistence/migrations/versions.py`` /
``postgres_versions.py``). ``reindex(paths)`` recomputes chunks for specific
files only and diffs by content hash so unchanged chunks are not rewritten —
the incremental-reindexing contract a ``repo.file.changed`` event handler
needs (:func:`enqueue_file_changed` registers the job type that drives it).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from backend.jobs.queue import get_queue, register_handler
from backend.observability.tracing import trace_indexing
from backend.persistence.database import get_store
from backend.persistence.tenancy import DEFAULT_TENANT_ID
from backend.repository.chunking import Chunk, chunk_source

#: Source file extensions walked by :func:`index`. Scoped to Python for
#: E7-S1 (see ``backend/repository/providers/treesitter_provider.py``).
_INDEXED_EXTENSIONS = {".py"}

#: Files reindexed per connection/transaction (E45-S5) — bounds how long a
#: single transaction stays open while still batching far more than one
#: statement per file.
_REINDEX_BATCH_SIZE = 200

_IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


def index(repo_path: str | Path, *, tenant_id: str = DEFAULT_TENANT_ID, store: Any | None = None) -> int:
    """Index every source file under *repo_path*, persisting chunk metadata.

    Args:
        repo_path: Root directory to walk.
        tenant_id: Tenant to scope persisted chunks to.
        store: Durable store to persist into; defaults to :func:`get_store`.

    Returns:
        Total number of chunk rows written (inserted or updated) across every
        file — unchanged chunks (same file/symbol/span with an identical
        content hash) are not counted.
    """
    with trace_indexing("index", tenant_id=tenant_id) as measurements:
        root = Path(repo_path).resolve()
        files = [str(path) for path in _iter_source_files(root)]
        measurements.file_count = len(files)
        written = reindex(files, repo_root=root, tenant_id=tenant_id, store=store)
        measurements.chunks_written = written
        return written


def reindex(
    paths: Iterable[str],
    *,
    repo_root: Path | None = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    store: Any | None = None,
) -> int:
    """Recompute chunks for specific files and persist only changed ones.

    A chunk unchanged since the last run (same file path, symbol, start
    line, and content hash already stored) is left untouched. A chunk that no
    longer exists for a file (e.g. a removed function, or the file itself
    was deleted) is deleted from the store.

    Args:
        paths: File paths to reindex (absolute, or relative to *repo_root*).
        repo_root: Root used to compute each file's stored (relative) path;
            defaults to the current working directory.
        tenant_id: Tenant to scope persisted chunks to.
        store: Durable store to persist into; defaults to :func:`get_store`.

    Returns:
        Number of chunk rows written (inserted or updated); unchanged rows do
        not count.
    """
    active_store = store if store is not None else get_store()
    param = _param_style(active_store)
    root = (repo_root or Path.cwd()).resolve()
    path_list = list(paths)
    written = 0
    with trace_indexing("reindex", tenant_id=tenant_id) as measurements:
        for batch_start in range(0, len(path_list), _REINDEX_BATCH_SIZE):
            batch = path_list[batch_start : batch_start + _REINDEX_BATCH_SIZE]
            with active_store.connect() as conn:
                for raw_path in batch:
                    measurements.file_count += 1
                    candidate = Path(raw_path)
                    absolute = candidate if candidate.is_absolute() else (root / candidate)
                    relative = _relative_path(absolute, root)
                    if not absolute.is_file():
                        measurements.chunks_deleted += _delete_chunks_for_file(
                            conn, param, relative, tenant_id
                        )
                        continue
                    code = absolute.read_text(encoding="utf-8", errors="replace")
                    chunks = chunk_source(relative, code, "python")
                    written += _persist_chunks(conn, param, relative, chunks, tenant_id)
                conn.commit()
        measurements.chunks_written = written
    return written


@register_handler("repo.index.reindex_file")
def _handle_reindex_file_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Job handler: reindex a single file's chunks (E7-S1-T3).

    Registered against :func:`backend.jobs.queue.register_handler` so a
    ``repo.file.changed`` event handler can drive incremental reindexing by
    calling :func:`enqueue_file_changed`, without the event handler itself
    needing to know how chunking/persistence works.

    Args:
        payload: ``{"path": str, "repo_root": str, "tenant_id": str}`` as
            built by :func:`enqueue_file_changed`.

    Returns:
        ``{"path": ..., "chunks_written": int}``.
    """
    path = payload["path"]
    repo_root = Path(payload.get("repo_root", "."))
    tenant_id = payload.get("tenant_id", DEFAULT_TENANT_ID)
    written = reindex([path], repo_root=repo_root, tenant_id=tenant_id)
    return {"path": path, "chunks_written": written}


def enqueue_file_changed(
    path: str, *, repo_root: str | Path = ".", tenant_id: str = DEFAULT_TENANT_ID
) -> str:
    """Enqueue incremental reindexing for a single changed file (E7-S1-T3).

    Intended to be called from a ``repo.file.changed`` event handler.

    Args:
        path: Path of the file that changed.
        repo_root: Root used to resolve *path* and compute its stored relative path.
        tenant_id: Tenant to scope the reindex to.

    Returns:
        The job id returned by the active queue's ``enqueue`` (see
        :func:`backend.jobs.queue.get_queue`).
    """
    queue = get_queue()
    return queue.enqueue(
        "repo.index.reindex_file",
        {"path": str(path), "repo_root": str(repo_root), "tenant_id": tenant_id},
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _param_style(store: Any) -> str:
    """Return the SQL placeholder style for *store*'s underlying connection."""
    url = str(getattr(store, "database_url", ""))
    return "%s" if url.startswith(("postgresql://", "postgres://")) else "?"


def _persist_chunks(conn: Any, param: str, file_path: str, chunks: list[Chunk], tenant_id: str) -> int:
    """Upsert *chunks* for *file_path* on an already-open connection.

    Skips any chunk whose content hash is unchanged, and deletes any
    previously stored chunk for *file_path* that no longer corresponds to a
    chunk in *chunks* (e.g. a removed function). Upserts and deletes are each
    issued as a single ``executemany`` batch (E45-S5) rather than one
    statement per chunk; the caller owns the transaction (commits the batch
    of files this call is part of).

    Args:
        conn: Open connection from the caller's batch (not committed here).
        param: SQL placeholder style for *conn* (see :func:`_param_style`).
        file_path: Stored (relative) path the chunks belong to.
        chunks: Freshly computed chunks for *file_path*.
        tenant_id: Tenant to scope persisted rows to.

    Returns:
        Number of rows inserted or updated (unchanged rows do not count).
    """
    existing = {
        (row[0], row[1]): row[2]
        for row in conn.execute(
            f"SELECT symbol, start_line, content_hash FROM code_chunks "
            f"WHERE tenant_id = {param} AND file_path = {param}",
            (tenant_id, file_path),
        ).fetchall()
    }
    desired_keys: set[tuple[str, int]] = set()
    to_upsert: list[Chunk] = []
    for chunk in chunks:
        key = (chunk.symbol, chunk.start_line)
        desired_keys.add(key)
        if existing.get(key) != chunk.content_hash:
            to_upsert.append(chunk)

    if to_upsert:
        conn.cursor().executemany(
            f"""
            INSERT INTO code_chunks
                (tenant_id, file_path, symbol, start_line, end_line, content_hash, content)
            VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param})
            ON CONFLICT(tenant_id, file_path, symbol, start_line) DO UPDATE SET
                end_line = excluded.end_line,
                content_hash = excluded.content_hash,
                content = excluded.content,
                indexed_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    tenant_id,
                    file_path,
                    chunk.symbol,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.content_hash,
                    chunk.content,
                )
                for chunk in to_upsert
            ],
        )

    stale_keys = set(existing) - desired_keys
    if stale_keys:
        conn.cursor().executemany(
            f"DELETE FROM code_chunks WHERE tenant_id = {param} AND file_path = {param} "
            f"AND symbol = {param} AND start_line = {param}",
            [(tenant_id, file_path, symbol, start_line) for symbol, start_line in stale_keys],
        )
    return len(to_upsert)


def _delete_chunks_for_file(conn: Any, param: str, file_path: str, tenant_id: str) -> int:
    """Remove all persisted chunks for a file that no longer exists on disk.

    Args:
        conn: Open connection from the caller's batch (not committed here).
        param: SQL placeholder style for *conn* (see :func:`_param_style`).
        file_path: Repository-relative path whose chunks are removed.
        tenant_id: Tenant the chunks are scoped to.

    Returns:
        Number of chunk rows deleted, or ``0`` when the driver does not report
        a row count.
    """
    cursor = conn.execute(
        f"DELETE FROM code_chunks WHERE tenant_id = {param} AND file_path = {param}",
        (tenant_id, file_path),
    )
    rowcount = getattr(cursor, "rowcount", 0)
    return rowcount if isinstance(rowcount, int) and rowcount > 0 else 0


def _iter_source_files(root: Path) -> Iterable[Path]:
    """Stream every indexable source file under *root*, pruning ignored directories.

    Uses ``os.walk`` with in-place ``dirnames`` pruning (E45-S5) so an
    ignored directory (``.venv``, ``node_modules``, ...) is never descended
    into at all — unlike ``sorted(root.rglob("*"))``, which materializes and
    sorts the full recursive listing (including ignored subtrees) before
    filtering.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED_DIRECTORIES)
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if path.suffix in _INDEXED_EXTENSIONS:
                yield path


def _relative_path(path: Path, root: Path) -> str:
    """Return *path* as a string relative to *root* when possible, else its absolute string."""
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


__all__ = ["enqueue_file_changed", "index", "reindex"]
