"""Unit tests for the ``patches`` CLI plugin (backend/cli_plugins/patches.py).

Covers ``patches generate`` and ``patches apply`` end-to-end through
``backend.cli.main``, including the dry-run default, ``--enable`` override,
the ``AUTODEV_ENABLE_PATCH_APPLY=1`` environment override, the no-changes
diff case, and the path-traversal rejection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest

from backend.cli import main
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Isolate each test in its own database, config file, and working directory."""
    database_path = tmp_path / "cli.db"
    config_path = tmp_path / "autodev.config.json"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("AUTODEV_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("AUTODEV_ENABLE_PATCH_APPLY", raising=False)
    monkeypatch.chdir(tmp_path)
    reset_store_cache()
    reset_settings_cache()

    yield

    reset_store_cache()
    reset_settings_cache()


def test_patches_generate_prints_unified_diff(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``patches generate`` prints a unified diff when contents differ."""
    original_file = tmp_path / "original.txt"
    updated_file = tmp_path / "updated.txt"
    original_file.write_text("line one\nline two\n")
    updated_file.write_text("line one\nline three\n")

    exit_code = main(
        [
            "patches",
            "generate",
            "--path",
            "example.txt",
            "--original-file",
            str(original_file),
            "--updated-file",
            str(updated_file),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "-line two" in captured.out
    assert "+line three" in captured.out
    assert "a/example.txt" in captured.out


def test_patches_generate_reports_no_changes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``patches generate`` prints a friendly marker when there is no diff."""
    same_file = tmp_path / "same.txt"
    same_file.write_text("identical\n")

    exit_code = main(
        [
            "patches",
            "generate",
            "--path",
            "example.txt",
            "--original-file",
            str(same_file),
            "--updated-file",
            str(same_file),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "(no changes)"


def test_patches_generate_without_files_uses_empty_content(capsys: pytest.CaptureFixture[str]) -> None:
    """Omitting ``--original-file``/``--updated-file`` treats content as empty strings."""
    exit_code = main(["patches", "generate", "--path", "example.txt"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "(no changes)"


def test_patches_apply_dry_run_by_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``patches apply`` without ``--enable`` performs a dry-run and writes nothing."""
    updated_file = tmp_path / "updated.txt"
    updated_file.write_text("new content\n")
    root = tmp_path / "workspace"
    root.mkdir()

    exit_code = main(
        [
            "patches",
            "apply",
            "--path",
            "generated.txt",
            "--updated-file",
            str(updated_file),
            "--root",
            str(root),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["applied"] is False
    assert payload["dry_run"] is True
    assert not (root / "generated.txt").exists()


def test_patches_apply_with_enable_writes_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Passing ``--enable`` forces the patch to be written to disk."""
    updated_file = tmp_path / "updated.txt"
    updated_file.write_text("new content\n")
    root = tmp_path / "workspace"
    root.mkdir()

    exit_code = main(
        [
            "patches",
            "apply",
            "--path",
            "generated.txt",
            "--updated-file",
            str(updated_file),
            "--root",
            str(root),
            "--enable",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["applied"] is True
    assert payload["dry_run"] is False
    assert (root / "generated.txt").read_text() == "new content\n"


def test_patches_apply_env_var_forces_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``AUTODEV_ENABLE_PATCH_APPLY=1`` forces a write even without ``--enable``."""
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "1")
    updated_file = tmp_path / "updated.txt"
    updated_file.write_text("env-enabled content\n")
    root = tmp_path / "workspace"
    root.mkdir()

    exit_code = main(
        [
            "patches",
            "apply",
            "--path",
            "generated.txt",
            "--updated-file",
            str(updated_file),
            "--root",
            str(root),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["applied"] is True
    assert (root / "generated.txt").read_text() == "env-enabled content\n"


def test_patches_apply_rejects_path_traversal(tmp_path: Path) -> None:
    """A ``--path`` that escapes ``--root`` raises ``ValueError`` from the patch engine."""
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(ValueError, match="Path traversal rejected"):
        main(
            [
                "patches",
                "apply",
                "--path",
                "../escape.txt",
                "--root",
                str(root),
                "--enable",
            ]
        )
