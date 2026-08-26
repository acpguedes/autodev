"""Trial contract case proving the harness itself (E56-S1 DoD).

One case, written once, executed against both backends via the ``backend``
fixture -- no conditional on which backend is under test.
"""

from __future__ import annotations

import uuid

from backend.tests.persistence_contract.conftest import SqlStore


def test_create_and_get_session_round_trips(sql_store: SqlStore) -> None:
    session_id = f"contract-trial-{uuid.uuid4().hex}"

    sql_store.create_session(
        session_id=session_id,
        goal="prove the contract harness works",
        plan=["step-1", "step-2"],
        artifacts={"note": "trial"},
    )

    session = sql_store.get_session(session_id)

    assert session is not None
    assert session["goal"] == "prove the contract harness works"
    assert session["plan"] == ["step-1", "step-2"]
    assert session["artifacts"] == {"note": "trial"}
