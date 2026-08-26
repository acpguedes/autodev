"""Proves the removed PostgreSQL fallback never re-creates a local file (E55-S3-T2/T3).

Before E55, ``StepApprovalStore`` fell back to a standalone SQLite file
(``AUTODEV_PLAN_STEP_STATE_DB``, default ``./autodev_plan_step_state.db``)
whenever ``DATABASE_URL`` was unset or pointed at PostgreSQL. E55-S1 removed
that fallback for good: the store now always resolves its connection
through ``get_store()``, the same dispatch every other ``/v2`` store uses.
This test proves the negative directly -- a PostgreSQL ``DATABASE_URL`` that
cannot be reached fails loudly (a connection error) instead of silently
succeeding by writing a file into the working directory, and no ``.db`` file
of any name appears there as a side effect either way.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    reset_settings_cache()
    reset_store_cache()
    yield
    reset_settings_cache()
    reset_store_cache()


def test_unreachable_postgres_database_url_creates_no_local_sqlite_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PostgreSQL ``DATABASE_URL`` fails to connect rather than falling back to a local file."""
    monkeypatch.chdir(tmp_path)
    # Port 1 is a well-known reserved port no PostgreSQL server binds to, so
    # this connection attempt fails fast and deterministically without
    # requiring a real PostgreSQL instance in this test environment.
    monkeypatch.setenv("DATABASE_URL", "postgresql://autodev:autodev@127.0.0.1:1/autodev_e55_test")
    monkeypatch.delenv("AUTODEV_PLAN_STEP_STATE_DB", raising=False)
    reset_settings_cache()
    reset_store_cache()

    from backend.plans.step_state import StepApprovalStore

    with pytest.raises(Exception):  # noqa: B017 - any connection failure proves the point; not a fallback
        StepApprovalStore()

    assert list(tmp_path.glob("*.db")) == [], (
        "no standalone SQLite file was created for a PostgreSQL DATABASE_URL"
    )
    assert not (tmp_path / "autodev_plan_step_state.db").exists()


def test_legacy_fallback_env_var_no_longer_selects_the_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting the legacy escape hatch alongside a PostgreSQL URL has no effect on where the store connects."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://autodev:autodev@127.0.0.1:1/autodev_e55_test")
    monkeypatch.setenv("AUTODEV_PLAN_STEP_STATE_DB", str(tmp_path / "should-not-be-created.db"))
    reset_settings_cache()
    reset_store_cache()

    from backend.plans.step_state import StepApprovalStore

    with pytest.raises(Exception):  # noqa: B017 - see above
        StepApprovalStore()

    assert not (tmp_path / "should-not-be-created.db").exists()
