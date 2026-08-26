"""Shared fixtures for the contract suite (E56-S1).

``backend`` (from :mod:`backend.tests.contract.backends`) is the only
fixture that knows which dialect is under test. Everything below builds on
top of it so contract case bodies only ever see ``sql_store`` (or one of the
E51-E55 store wrappers) and never branch on backend identity themselves.
"""

from __future__ import annotations

from typing import Union

import pytest

from backend.environments.store import EnvironmentStore
from backend.execution.policy import PolicyStore
from backend.persistence.postgres_adapter import PostgresPlanStore, PostgresStore
from backend.persistence.sqlite_adapter import SQLitePlanStore, SQLiteStore, _resolve_db_path
from backend.plans.step_state import StepApprovalStore
from backend.quotas.store import QuotaStore
from backend.secret_store.store import SecretStore
from backend.tests.persistence_contract.backends import Backend, backend  # noqa: F401 -- re-exported fixture

SqlStore = Union[SQLiteStore, PostgresStore]
PlanStoreImpl = Union[SQLitePlanStore, PostgresPlanStore]


@pytest.fixture
def sql_store(backend: Backend) -> SqlStore:  # noqa: F811 -- pytest fixture injection by name
    """Build the base store (sessions/runs/messages/eval scoring) for *backend*.

    Both concrete stores self-migrate in ``__init__``
    (``backend/persistence/{sqlite_adapter,postgres_adapter}/store.py``), so
    building one against a fresh database is already a from-empty migration
    run.
    """
    if backend.is_postgres:
        return PostgresStore(backend.database_url)
    return SQLiteStore(backend.database_url)


@pytest.fixture
def quota_store(sql_store: SqlStore) -> QuotaStore:
    return QuotaStore(store=sql_store)


@pytest.fixture
def secret_store(sql_store: SqlStore) -> SecretStore:
    return SecretStore(store=sql_store)


@pytest.fixture
def policy_store(sql_store: SqlStore) -> PolicyStore:
    return PolicyStore(store=sql_store)


@pytest.fixture
def environment_store(sql_store: SqlStore) -> EnvironmentStore:
    return EnvironmentStore(store=sql_store)


@pytest.fixture
def step_approval_store(sql_store: SqlStore) -> StepApprovalStore:
    return StepApprovalStore(store=sql_store)


@pytest.fixture
def plan_store(backend: Backend) -> PlanStoreImpl:  # noqa: F811 -- pytest fixture injection by name
    """Build the ``PlanRepository`` implementation for *backend*.

    Bypasses ``backend.plans.store.PlanStore``'s factory: it dispatches on
    ``DATABASE_URL``'s dialect prefix but ignores a ``sqlite://`` URL and
    falls back to ``SQLitePlanStore``'s own default path, which would break
    this fixture's per-test database isolation.
    """
    if backend.is_postgres:
        return PostgresPlanStore(database_url=backend.database_url)
    return SQLitePlanStore(db_path=_resolve_db_path(backend.database_url))
