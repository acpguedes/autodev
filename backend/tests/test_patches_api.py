"""Tests for the patches API router and CLI plugin — U13."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.cli import build_parser

client = TestClient(app)


def test_generate_returns_unified_diff() -> None:
    response = client.post(
        "/patches/generate",
        json={"path": "f.py", "original": "alpha\nbeta\n", "updated": "alpha\ngamma\n"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "f.py"
    assert body["diff"]  # non-empty unified diff
    assert "-beta" in body["diff"]
    assert "+gamma" in body["diff"]


def test_generate_empty_diff_when_unchanged() -> None:
    response = client.post(
        "/patches/generate",
        json={"path": "f.py", "original": "same\n", "updated": "same\n"},
    )
    assert response.status_code == 200
    assert response.json()["diff"] == ""


def test_apply_is_dry_run_by_default() -> None:
    response = client.post(
        "/patches/apply",
        json={"path": "f.py", "original": "a\n", "updated": "b\n", "diff": ""},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is False
    assert body["dry_run"] is True


def test_cli_patches_generate(tmp_path, capsys) -> None:
    original = tmp_path / "orig.txt"
    updated = tmp_path / "new.txt"
    original.write_text("one\ntwo\n", encoding="utf-8")
    updated.write_text("one\nthree\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(
        [
            "patches",
            "generate",
            "--path",
            "demo.txt",
            "--original-file",
            str(original),
            "--updated-file",
            str(updated),
        ]
    )
    exit_code = args.handler(args)
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "-two" in captured.out
    assert "+three" in captured.out
