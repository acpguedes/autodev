"""Tests for U11 — Plans CLI: show, approve, reject.

Uses ``backend.cli.build_parser()`` and direct handler invocation — no
subprocess spawning required.  Each test gets an isolated SQLite DB via the
``isolated_runtime`` fixture.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Generator

import pytest

from backend.persistence.database import reset_store_cache


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    db_path = tmp_path / "cli-plans-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.chdir(tmp_path)
    reset_store_cache()
    yield
    reset_store_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_plan(session_id: str, steps: list[str]) -> None:
    """Insert a plan directly via PlanStore (bypasses CLI for setup)."""
    from backend.plans import PlanStore  # noqa: PLC0415

    db_url = os.environ.get("DATABASE_URL", "")
    db_path: Path | None = None
    if db_url.startswith("sqlite:///"):
        raw = db_url.removeprefix("sqlite:///")
        db_path = Path(raw).expanduser().resolve()

    store = PlanStore(db_path=db_path)
    store.upsert_plan(session_id, steps)


def _run_plans_command(argv: list[str]) -> tuple[int, str]:
    """Build parser, invoke handler, capture printed JSON.

    Returns (exit_code, stdout_text).
    """
    import io
    import sys

    from backend.cli import build_parser  # noqa: PLC0415

    parser = build_parser()
    args = parser.parse_args(argv)
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        rc = args.handler(args)
    finally:
        sys.stdout = old_stdout
    return rc, captured.getvalue()


SESSION_ID = "plans-cli-session-001"


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_show_exits_1_when_absent(isolated_runtime: None) -> None:
    rc, _ = _run_plans_command(["plans", "show", SESSION_ID])
    assert rc == 1


def test_show_exits_0_when_present(isolated_runtime: None) -> None:
    _seed_plan(SESSION_ID, ["step-a", "step-b"])
    rc, _ = _run_plans_command(["plans", "show", SESSION_ID])
    assert rc == 0


def test_show_output_is_valid_json(isolated_runtime: None) -> None:
    _seed_plan(SESSION_ID, ["step-x"])
    _, output = _run_plans_command(["plans", "show", SESSION_ID])
    data = json.loads(output)
    assert data["session_id"] == SESSION_ID


def test_show_output_contains_steps(isolated_runtime: None) -> None:
    _seed_plan(SESSION_ID, ["s1", "s2", "s3"])
    _, output = _run_plans_command(["plans", "show", SESSION_ID])
    data = json.loads(output)
    assert data["steps"] == ["s1", "s2", "s3"]


def test_show_output_status_is_draft(isolated_runtime: None) -> None:
    _seed_plan(SESSION_ID, ["s"])
    _, output = _run_plans_command(["plans", "show", SESSION_ID])
    data = json.loads(output)
    assert data["status"] == "draft"


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------


def test_approve_exits_1_when_absent(isolated_runtime: None) -> None:
    rc, _ = _run_plans_command(["plans", "approve", SESSION_ID, "--actor", "alice"])
    assert rc == 1


def test_approve_exits_0(isolated_runtime: None) -> None:
    _seed_plan(SESSION_ID, ["s"])
    rc, _ = _run_plans_command(["plans", "approve", SESSION_ID, "--actor", "alice"])
    assert rc == 0


def test_approve_output_status_approved(isolated_runtime: None) -> None:
    _seed_plan(SESSION_ID, ["s"])
    _, output = _run_plans_command(
        ["plans", "approve", SESSION_ID, "--actor", "alice", "--note", "looks good"]
    )
    data = json.loads(output)
    assert data["status"] == "approved"


def test_approve_output_is_valid_json(isolated_runtime: None) -> None:
    _seed_plan(SESSION_ID, ["s"])
    _, output = _run_plans_command(["plans", "approve", SESSION_ID, "--actor", "alice"])
    data = json.loads(output)
    assert data["session_id"] == SESSION_ID


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------


def test_reject_exits_1_when_absent(isolated_runtime: None) -> None:
    rc, _ = _run_plans_command(["plans", "reject", SESSION_ID, "--actor", "bob"])
    assert rc == 1


def test_reject_exits_0(isolated_runtime: None) -> None:
    _seed_plan(SESSION_ID, ["s"])
    rc, _ = _run_plans_command(["plans", "reject", SESSION_ID, "--actor", "bob"])
    assert rc == 0


def test_reject_output_status_rejected(isolated_runtime: None) -> None:
    _seed_plan(SESSION_ID, ["s"])
    _, output = _run_plans_command(
        ["plans", "reject", SESSION_ID, "--actor", "bob", "--note", "needs revision"]
    )
    data = json.loads(output)
    assert data["status"] == "rejected"


def test_reject_output_is_valid_json(isolated_runtime: None) -> None:
    _seed_plan(SESSION_ID, ["s"])
    _, output = _run_plans_command(["plans", "reject", SESSION_ID, "--actor", "bob"])
    data = json.loads(output)
    assert data["session_id"] == SESSION_ID


# ---------------------------------------------------------------------------
# approve → show round-trip
# ---------------------------------------------------------------------------


def test_approve_then_show_status_is_approved(isolated_runtime: None) -> None:
    _seed_plan(SESSION_ID, ["s"])
    _run_plans_command(["plans", "approve", SESSION_ID, "--actor", "alice"])
    _, output = _run_plans_command(["plans", "show", SESSION_ID])
    data = json.loads(output)
    assert data["status"] == "approved"
