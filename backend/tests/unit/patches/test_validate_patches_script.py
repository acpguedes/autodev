"""Unit tests for the patch-validation CI gate (`scripts/validate_patches.py`).

Protects the E12-S4-T2 gate behavior: the script must pass against the real
patch engine and must surface a failure when a safety property is violated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.patches.models import Patch, PatchResult
from scripts import validate_patches


def test_run_checks_passes_against_real_engine() -> None:
    """The gate reports no failures when run against the real patch engine."""
    assert validate_patches.run_checks() == []


def test_main_returns_zero_on_success(capsys: pytest.CaptureFixture[str]) -> None:
    """`main()` exits 0 and prints a success line when all checks pass."""
    assert validate_patches.main() == 0
    assert "passed" in capsys.readouterr().out


def test_dry_run_check_rejects_any_filesystem_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dry-run check fails when the engine creates any workspace entry."""
    root = tmp_path / "workspace"
    root.mkdir()

    real_apply_patch = validate_patches.apply_patch

    def leaking_apply_patch(
        patch: Patch,
        root: str = ".",
        enable: bool | None = None,
    ) -> PatchResult:
        """Delegate to the engine, then simulate an unrelated dry-run leak."""
        result = real_apply_patch(patch, root=root, enable=enable)
        leaked = Path(root) / "unrelated" / "leaked.txt"
        leaked.parent.mkdir()
        leaked.write_text("leaked\n", encoding="utf-8")
        return result

    monkeypatch.setattr(validate_patches, "apply_patch", leaking_apply_patch)

    with pytest.raises(validate_patches.PatchValidationError, match="filesystem"):
        validate_patches.check_dry_run_does_not_write(root)


def test_path_traversal_check_passes_when_guard_holds(tmp_path: Path) -> None:
    """The path-traversal check passes because the engine guard rejects escapes."""
    root = tmp_path / "workspace"
    root.mkdir()
    # Should not raise: the engine rejects the escaping path and writes nothing.
    validate_patches.check_path_traversal_rejected(root)
    assert not (tmp_path / "escaped.txt").exists()
