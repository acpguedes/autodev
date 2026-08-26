"""Transaction and error-equivalence contract cases (E56-S2-T3).

A uniqueness breach must raise the same shared exception type on both
backends -- :class:`~backend.persistence.contract.PersistenceIntegrityError`
-- not a backend-specific one (``sqlite3.IntegrityError`` vs
``psycopg.errors.UniqueViolation``). Before this story, ``create_session``
raised the raw backend-specific type on each backend; this test pins the
fix.
"""

from __future__ import annotations

import uuid

import pytest

from backend.persistence.contract import PersistenceIntegrityError
from backend.tests.persistence_contract.conftest import SqlStore


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def test_duplicate_session_id_raises_the_shared_integrity_error(sql_store: SqlStore) -> None:
    session_id = _uid("session")
    sql_store.create_session(session_id=session_id, goal="g", plan=[], artifacts={})

    with pytest.raises(PersistenceIntegrityError):
        sql_store.create_session(session_id=session_id, goal="g2", plan=[], artifacts={})

    # The failed write did not partially apply -- the original row is untouched.
    session = sql_store.get_session(session_id)
    assert session is not None
    assert session["goal"] == "g"


def test_failed_write_does_not_leave_a_partial_row_behind(sql_store: SqlStore) -> None:
    session_id = _uid("session")
    sql_store.create_session(session_id=session_id, goal="original", plan=[], artifacts={})

    with pytest.raises(PersistenceIntegrityError):
        sql_store.create_session(session_id=session_id, goal="clobbered", plan=[], artifacts={})

    assert len(sql_store.list_sessions()) == 1
