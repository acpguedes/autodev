#!/usr/bin/env python3
"""Patch-validation gate for the CI Validation Gates (E12-S4-T2).

Exercises the E0 patch engine (`backend.patches.engine.apply_patch`) against a
throwaway workspace to prove two safety properties hold before any change is
allowed to merge:

1. **Dry-run does not write.** Applying a patch with ``enable=False`` reports
   what would change but must leave the filesystem untouched.
2. **Path-traversal guard holds.** A patch whose path resolves outside the
   workspace root must be rejected (``ValueError``) even when a real apply is
   requested, and nothing may be written outside the root.

The check is deterministic, needs no network or services, and exits non-zero on
any failure so it can be wired as a mandatory CI gate and run locally via
``make validate-patches``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Allow running as a bare script (`python scripts/validate_patches.py`): ensure
# the repository root is importable so `backend` resolves without an install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.patches.engine import apply_patch, generate_patch  # noqa: E402
from backend.patches.models import Patch  # noqa: E402


class PatchValidationError(RuntimeError):
    """Raised when a patch-engine safety property does not hold."""


def check_dry_run_does_not_write(root: Path) -> None:
    """Assert a dry-run apply reports a no-write outcome and touches no file.

    Args:
        root: Workspace root the patch is applied against.

    Raises:
        PatchValidationError: If the dry-run claims to have applied the patch,
            or if it writes the target file to disk.
    """
    target_rel = "src/example.txt"
    patch = generate_patch(target_rel, original="old\n", updated="new\n")

    result = apply_patch(patch, root=str(root), enable=False)

    if result.applied or not result.dry_run:
        raise PatchValidationError(
            "Dry-run apply must not report applied=True/dry_run=False; "
            f"got applied={result.applied}, dry_run={result.dry_run}."
        )
    if (root / target_rel).exists():
        raise PatchValidationError(
            f"Dry-run apply wrote {target_rel!r} to disk; it must not touch the filesystem."
        )


def check_path_traversal_rejected(root: Path) -> None:
    """Assert an escaping patch path is rejected and writes nothing outside root.

    Args:
        root: Workspace root the patch must be confined to.

    Raises:
        PatchValidationError: If an escaping path is not rejected, or if a file
            is written outside the workspace root.
    """
    escaping = "../escaped.txt"
    patch = Patch(path=escaping, original="", updated="pwned\n", diff="")

    outside_target = (root.parent / "escaped.txt").resolve()
    try:
        apply_patch(patch, root=str(root), enable=True)
    except ValueError:
        pass  # Expected: the path-traversal guard rejects the apply.
    else:
        raise PatchValidationError(
            f"Path-traversal guard failed: {escaping!r} was accepted instead of rejected."
        )

    if outside_target.exists():
        raise PatchValidationError(
            f"Path-traversal apply wrote outside the root at {outside_target}."
        )


def run_checks() -> list[str]:
    """Run every patch-validation check in an isolated temporary workspace.

    Returns:
        A list of human-readable failure messages; empty when all checks pass.
    """
    checks = (
        ("dry-run does not write", check_dry_run_does_not_write),
        ("path-traversal guard rejects escapes", check_path_traversal_rejected),
    )
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="autodev-patch-gate-") as tmp:
        root = Path(tmp) / "workspace"
        root.mkdir()
        for name, check in checks:
            try:
                check(root)
            except PatchValidationError as exc:
                failures.append(f"{name}: {exc}")
    return failures


def main() -> int:
    """Run the patch-validation gate and report the outcome.

    Returns:
        ``0`` when every check passes, ``1`` otherwise.
    """
    failures = run_checks()
    if failures:
        print("Patch validation gate FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("Patch validation gate passed: dry-run and path-traversal guard verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
