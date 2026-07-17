"""Unit tests filling coverage gaps in the ``skills`` CLI plugin.

Complements ``backend/tests/test_skills_cli.py`` (not modified here) by
exercising the malformed ``--input`` branch of
``backend.cli_plugins.skills._handle_skills_invoke``, which none of the
existing tests reach.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest

from backend.persistence.database import reset_store_cache


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Isolate each test in its own database, config file, and working directory."""
    database_path = tmp_path / "cli.db"
    config_path = tmp_path / "autodev.config.json"
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "README.md").write_text("workspace root")

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(config_path))
    monkeypatch.chdir(tmp_path)
    reset_store_cache()

    yield

    reset_store_cache()


def _parse_and_run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """Build the parser, parse *args*, call handler, return (exit_code, stdout, stderr)."""
    from backend.cli import build_parser  # noqa: PLC0415

    parser = build_parser()
    ns = parser.parse_args(args)
    code: int = ns.handler(ns)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_skills_invoke_malformed_input_pair_returns_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    """A ``--input`` value with no ``=`` separator is rejected with exit code 1."""
    code, _, err = _parse_and_run(
        ["skills", "invoke", "summarize_diff", "--input", "no_equals_sign_here"],
        capsys,
    )

    assert code == 1
    payload = json.loads(err)
    assert "Invalid --input format" in payload["error"]
    assert "no_equals_sign_here" in payload["error"]


def test_skills_invoke_malformed_input_stops_before_invoking(capsys: pytest.CaptureFixture[str]) -> None:
    """A malformed pair short-circuits before any well-formed pairs are applied."""
    code, out, _ = _parse_and_run(
        ["skills", "invoke", "summarize_diff", "--input", "diff=x", "--input", "bad_pair"],
        capsys,
    )

    assert code == 1
    assert out == ""


def test_skills_invoke_unknown_skill_reports_key_error_message(capsys: pytest.CaptureFixture[str]) -> None:
    """Invoking an unregistered skill surfaces the ``KeyError`` message as JSON on stderr."""
    code, out, err = _parse_and_run(["skills", "invoke", "definitely_not_a_real_skill"], capsys)

    assert code == 1
    assert out == ""
    payload = json.loads(err)
    assert "error" in payload
