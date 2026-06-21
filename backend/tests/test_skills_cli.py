"""Tests for U4 — Skills CLI plugin.

Uses the same isolation fixture as ``tests/backend/test_cli.py``
(tmp_path, monkeypatch env vars, chdir).  Exercises the plugin via
``backend.cli.build_parser()`` and direct handler invocation — no subprocess
required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest

from backend.persistence.database import reset_store_cache


# ---------------------------------------------------------------------------
# Isolation fixture (mirrors tests/backend/test_cli.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_and_run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """Build the parser, parse *args*, call handler, return (exit_code, stdout)."""
    from backend.cli import build_parser  # noqa: PLC0415

    parser = build_parser()
    ns = parser.parse_args(args)
    code: int = ns.handler(ns)
    captured = capsys.readouterr()
    return code, captured.out


# ---------------------------------------------------------------------------
# skills list
# ---------------------------------------------------------------------------


def test_skills_list_exit_code_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = _parse_and_run(["skills", "list"], capsys)
    assert code == 0


def test_skills_list_returns_json_list(capsys: pytest.CaptureFixture[str]) -> None:
    _, out = _parse_and_run(["skills", "list"], capsys)
    data = json.loads(out)
    assert isinstance(data, list)


def test_skills_list_contains_three_builtins(capsys: pytest.CaptureFixture[str]) -> None:
    _, out = _parse_and_run(["skills", "list"], capsys)
    names = {item["name"] for item in json.loads(out)}
    assert "summarize_diff" in names
    assert "extract_symbols_lexical" in names
    assert "render_checklist" in names


def test_skills_list_items_have_name_and_description(capsys: pytest.CaptureFixture[str]) -> None:
    _, out = _parse_and_run(["skills", "list"], capsys)
    for item in json.loads(out):
        assert "name" in item
        assert "description" in item


# ---------------------------------------------------------------------------
# skills invoke
# ---------------------------------------------------------------------------

SAMPLE_DIFF = """\
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,5 @@
 line
+added_one
+added_two
-removed
"""


def test_skills_invoke_summarize_diff_exit_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = _parse_and_run(
        ["skills", "invoke", "summarize_diff", "--input", f"diff={SAMPLE_DIFF}"],
        capsys,
    )
    assert code == 0


def test_skills_invoke_summarize_diff_counts(capsys: pytest.CaptureFixture[str]) -> None:
    _, out = _parse_and_run(
        ["skills", "invoke", "summarize_diff", "--input", f"diff={SAMPLE_DIFF}"],
        capsys,
    )
    body = json.loads(out)
    assert body["success"] is True
    assert body["data"]["added_lines"] == 2
    assert body["data"]["removed_lines"] == 1


def test_skills_invoke_unknown_skill_returns_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = _parse_and_run(["skills", "invoke", "no_such_skill_xyz"], capsys)
    assert code != 0


def test_skills_invoke_render_checklist_no_input(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _parse_and_run(["skills", "invoke", "render_checklist"], capsys)
    assert code == 0
    body = json.loads(out)
    assert "content" in body
