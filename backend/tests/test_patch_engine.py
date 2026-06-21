"""Tests for U12 patch engine (backend/patches/).

Assertions:
- generate_patch produces a non-empty unified diff when content differs.
- generate_patch produces an empty diff when content is identical.
- apply_patch in dry-run mode writes nothing.
- apply_patch with enable=True writes the updated content into a tmp dir.
- apply_patch rejects a path that escapes root (path-traversal guard).
- PatchResult fields are populated correctly.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.patches import Patch, PatchResult, apply_patch, generate_patch


# ---------------------------------------------------------------------------
# generate_patch
# ---------------------------------------------------------------------------


def test_generate_patch_produces_unified_diff() -> None:
    patch = generate_patch("foo.py", "a = 1\n", "a = 2\n")
    assert isinstance(patch, Patch)
    assert patch.path == "foo.py"
    assert patch.original == "a = 1\n"
    assert patch.updated == "a = 2\n"
    assert "-a = 1" in patch.diff
    assert "+a = 2" in patch.diff


def test_generate_patch_empty_diff_when_identical() -> None:
    patch = generate_patch("same.py", "x = 1\n", "x = 1\n")
    assert patch.diff == ""


def test_generate_patch_diff_contains_file_headers() -> None:
    patch = generate_patch("src/module.py", "old\n", "new\n")
    assert "a/src/module.py" in patch.diff
    assert "b/src/module.py" in patch.diff


# ---------------------------------------------------------------------------
# apply_patch — dry-run (default)
# ---------------------------------------------------------------------------


def test_apply_patch_dry_run_writes_nothing(tmp_path: Path) -> None:
    patch = generate_patch("output.py", "x = 0\n", "x = 99\n")
    result = apply_patch(patch, root=str(tmp_path))

    assert isinstance(result, PatchResult)
    assert result.dry_run is True
    assert result.applied is False
    # File must NOT have been created.
    assert not (tmp_path / "output.py").exists()


def test_apply_patch_dry_run_via_enable_false(tmp_path: Path) -> None:
    patch = generate_patch("out.py", "a\n", "b\n")
    result = apply_patch(patch, root=str(tmp_path), enable=False)
    assert result.dry_run is True
    assert not (tmp_path / "out.py").exists()


# ---------------------------------------------------------------------------
# apply_patch — writing enabled
# ---------------------------------------------------------------------------


def test_apply_patch_enable_true_writes_file(tmp_path: Path) -> None:
    patch = generate_patch("result.py", "old\n", "new\n")
    result = apply_patch(patch, root=str(tmp_path), enable=True)

    assert result.applied is True
    assert result.dry_run is False
    written = (tmp_path / "result.py").read_text(encoding="utf-8")
    assert written == "new\n"


def test_apply_patch_enable_via_env_var(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "1")
    patch = generate_patch("env.py", "before\n", "after\n")
    result = apply_patch(patch, root=str(tmp_path))
    assert result.applied is True
    assert (tmp_path / "env.py").read_text() == "after\n"


def test_apply_patch_env_var_zero_is_dry_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_PATCH_APPLY", "0")
    patch = generate_patch("zero.py", "a\n", "b\n")
    result = apply_patch(patch, root=str(tmp_path))
    assert result.dry_run is True
    assert not (tmp_path / "zero.py").exists()


def test_apply_patch_creates_subdirectories(tmp_path: Path) -> None:
    patch = generate_patch("sub/dir/file.py", "", "content\n")
    result = apply_patch(patch, root=str(tmp_path), enable=True)
    assert result.applied is True
    assert (tmp_path / "sub" / "dir" / "file.py").exists()


# ---------------------------------------------------------------------------
# Path-traversal guard
# ---------------------------------------------------------------------------


def test_apply_patch_rejects_traversal(tmp_path: Path) -> None:
    patch = generate_patch("../../etc/passwd", "old\n", "evil\n")
    with pytest.raises(ValueError, match="traversal"):
        apply_patch(patch, root=str(tmp_path), enable=True)
