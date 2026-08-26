"""Pagination contract cases (E56-S2-T2): stable, complete paging on both backends.

The property under test (introduced by E44-S3): paging through every page
with a fixed page size visits each row exactly once -- no duplicates, no
skips -- and the reported total matches the number of rows created.
"""

from __future__ import annotations

import uuid

from backend.tests.persistence_contract.conftest import SqlStore


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _paginate_all_ids(page_fn, *, page_size: int) -> tuple[list[str], int]:
    """Walk every page of *page_fn* (a ``list_*_page``-shaped callable) and collect ids."""
    ids: list[str] = []
    offset = 0
    total = None
    while True:
        page, page_total = page_fn(limit=page_size, offset=offset)
        total = page_total
        if not page:
            break
        ids.extend(row["id"] for row in page)
        offset += page_size
    return ids, total


def test_session_pagination_visits_every_row_exactly_once(sql_store: SqlStore) -> None:
    tenant_id = _uid("tenant")
    created_ids = [_uid("session") for _ in range(7)]
    for session_id in created_ids:
        sql_store.create_session(
            session_id=session_id, goal="g", plan=[], artifacts={}, tenant_id=tenant_id
        )

    ids, total = _paginate_all_ids(
        lambda *, limit, offset: sql_store.list_sessions_page(
            limit=limit, offset=offset, tenant_id=tenant_id
        ),
        page_size=3,
    )

    assert total == len(created_ids)
    assert sorted(ids) == sorted(created_ids)
    assert len(ids) == len(set(ids)), "a row was visited more than once across pages"


def test_run_pagination_visits_every_row_exactly_once(sql_store: SqlStore) -> None:
    tenant_id = _uid("tenant")
    session_id = _uid("session")
    sql_store.create_session(
        session_id=session_id, goal="g", plan=[], artifacts={}, tenant_id=tenant_id
    )
    created_ids = [_uid("run") for _ in range(5)]
    for run_id in created_ids:
        sql_store.create_run(
            run_id=run_id,
            session_id=session_id,
            status="running",
            run_type="agent",
            current_state="start",
            trigger_message="go",
            results=[],
            steps=[],
            tenant_id=tenant_id,
        )

    ids, total = _paginate_all_ids(
        lambda *, limit, offset: sql_store.list_runs_page(
            session_id, limit=limit, offset=offset, tenant_id=tenant_id
        ),
        page_size=2,
    )

    assert total == len(created_ids)
    assert sorted(ids) == sorted(created_ids)
    assert len(ids) == len(set(ids)), "a row was visited more than once across pages"
