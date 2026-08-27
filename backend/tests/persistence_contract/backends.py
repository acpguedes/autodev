"""Backend provisioning for the contract suite (E56-S1-T1/T2).

Each contract case is parameterized over :data:`BACKEND_NAMES` through the
``backend`` fixture in ``conftest.py``. This module holds the plumbing that
differs per backend -- a fresh SQLite file, or a freshly created and later
dropped PostgreSQL database -- so fixtures (not test bodies) are the only
place backend identity is visible.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest

from backend.tests.postgres_gate import REQUIRE_POSTGRES_ENV

#: Environment variable naming the *admin* PostgreSQL URL used to create and
#: drop per-test databases. Mirrors the convention already used by
#: ``backend/tests/unit/{quotas,secret_store,execution,environments,plans}/test_postgres_concurrency.py``,
#: generalized here from per-test tenant rows to per-test databases so each
#: contract run gets a real from-empty migration (S1-T2).
#:
#: This role must NOT be a PostgreSQL superuser (and must not have the
#: BYPASSRLS attribute). A superuser bypasses Row-Level Security
#: unconditionally, even on a table with ``FORCE ROW LEVEL SECURITY`` -- the
#: Postgres images' bootstrap ``POSTGRES_USER`` is a superuser by default,
#: so a locally spun-up dev container needs a second, ordinary role (``LOGIN
#: CREATEDB``, otherwise default privileges) for this suite's tenant
#: isolation cases to mean anything (E56-S3-T2: this was found the hard way
#: -- a superuser connection made every isolation case pass vacuously and
#: hid a real cross-transaction RLS bug in ``StepApprovalStore.ensure_steps``).
POSTGRES_ADMIN_URL_ENV = "AUTODEV_TEST_POSTGRES_URL"

#: Reason attached to a skipped PostgreSQL case -- explicit and named, never
#: silent, so a PostgreSQL-less run cannot be mistaken for a passing one.
POSTGRES_SKIP_REASON = f"requires {POSTGRES_ADMIN_URL_ENV} (a real PostgreSQL, E56)"

BACKEND_NAMES = ("sqlite", "postgres")


@dataclass(frozen=True)
class Backend:
    """One backend under test: its name (for labeling) and a ready database URL."""

    name: str
    database_url: str

    @property
    def is_postgres(self) -> bool:
        return self.name == "postgres"


def sqlite_backend(tmp_path: Path) -> Backend:
    """Build a fresh, empty SQLite database URL under *tmp_path*."""
    db_path = tmp_path / f"contract-{uuid.uuid4().hex}.db"
    return Backend(name="sqlite", database_url=f"sqlite:///{db_path}")


def postgres_admin_url() -> str | None:
    """Return the configured PostgreSQL admin URL, or ``None`` if unset."""
    return os.environ.get(POSTGRES_ADMIN_URL_ENV) or None


def provision_postgres_database(admin_url: str) -> str:
    """Create a fresh, empty PostgreSQL database and return its URL.

    Connects to *admin_url* (an existing database on the target server) to
    issue ``CREATE DATABASE`` for a uniquely named database, so each test
    gets migrations-from-empty isolation instead of sharing tenant rows in
    one persistent database.

    Args:
        admin_url: A PostgreSQL URL for an existing, reachable database on
            the server the new database should be created on.

    Returns:
        A PostgreSQL URL pointing at the newly created, empty database.
    """
    import psycopg

    db_name = f"contract_{uuid.uuid4().hex}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{db_name}"')
    return _replace_database_name(admin_url, db_name)


def drop_postgres_database(admin_url: str, database_url: str) -> None:
    """Drop the database created by :func:`provision_postgres_database`.

    Args:
        admin_url: The same admin URL passed to
            :func:`provision_postgres_database` -- used to connect and issue
            the ``DROP DATABASE``, since a database cannot drop itself.
        database_url: The URL returned by :func:`provision_postgres_database`.
    """
    import psycopg

    db_name = database_url.rsplit("/", 1)[-1]
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')


def _replace_database_name(url: str, db_name: str) -> str:
    """Return *url* with its trailing ``/<database>`` segment replaced by *db_name*."""
    base, _, _ = url.rpartition("/")
    return f"{base}/{db_name}"


@pytest.fixture(params=BACKEND_NAMES)
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Backend]:
    """Yield a ready :class:`Backend` for each of ``BACKEND_NAMES``.

    The PostgreSQL branch is an explicit, named skip when
    ``AUTODEV_TEST_POSTGRES_URL`` is unset (S1-T2) -- never a silent pass.
    On CI's PostgreSQL leg (``AUTODEV_REQUIRE_POSTGRES`` set), the same
    missing-URL condition fails the test instead, so a broken service
    container turns the leg red rather than quietly skipping (E57-S2-T2).
    """
    if request.param == "sqlite":
        yield sqlite_backend(tmp_path)
        return

    admin_url = postgres_admin_url()
    if admin_url is None:
        if os.environ.get(REQUIRE_POSTGRES_ENV):
            pytest.fail(POSTGRES_SKIP_REASON, pytrace=False)
        pytest.skip(POSTGRES_SKIP_REASON)
    database_url = provision_postgres_database(admin_url)
    try:
        yield Backend(name="postgres", database_url=database_url)
    finally:
        drop_postgres_database(admin_url, database_url)
