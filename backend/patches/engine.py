"""Patch generation and flag-gated application engine.

Stdlib only — no external dependencies.

Security
--------
``apply_patch`` rejects any path that resolves outside *root* (path-traversal
guard).  Writing is disabled by default; enable it by passing ``enable=True``
or by setting the environment variable ``AUTODEV_ENABLE_PATCH_APPLY=1``.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

from backend.patches.models import Patch, PatchResult


def generate_patch(path: str, original: str, updated: str) -> Patch:
    """Generate a unified diff between *original* and *updated* for *path*.

    Parameters
    ----------
    path:
        Logical file path used as the label in the diff header.
    original:
        Original file content.
    updated:
        New file content.

    Returns
    -------
    :class:`Patch` with ``diff`` set to the unified-diff string (empty string
    when there are no changes).
    """
    original_lines = original.splitlines(keepends=True)
    updated_lines = updated.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            updated_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    diff = "".join(diff_lines)
    return Patch(path=path, original=original, updated=updated, diff=diff)


def apply_patch(
    patch: Patch,
    root: str = ".",
    enable: bool | None = None,
) -> PatchResult:
    """Apply *patch*, writing the updated content to ``root / patch.path``.

    The write is skipped (dry-run) UNLESS:
    - ``enable`` is explicitly ``True``, **or**
    - the environment variable ``AUTODEV_ENABLE_PATCH_APPLY`` equals ``"1"``.

    Parameters
    ----------
    patch:
        The :class:`Patch` to apply.
    root:
        Filesystem root under which the target file must reside.  Used to
        detect and reject path-traversal attempts.
    enable:
        ``True`` to write unconditionally; ``False`` to dry-run unconditionally;
        ``None`` (default) to consult the environment variable.

    Returns
    -------
    :class:`PatchResult` describing what happened.

    Raises
    ------
    ValueError
        If the resolved target path escapes *root*.
    """
    resolved_root = Path(root).resolve()
    target = (resolved_root / patch.path).resolve()

    # Path-traversal guard.
    try:
        target.relative_to(resolved_root)
    except ValueError:
        raise ValueError(
            f"Path traversal rejected: {patch.path!r} resolves outside root {root!r}."
        )

    # Decide whether to write.
    if enable is True:
        write = True
    elif enable is False:
        write = False
    else:
        write = os.environ.get("AUTODEV_ENABLE_PATCH_APPLY", "0") == "1"

    if not write:
        return PatchResult(
            path=patch.path,
            applied=False,
            dry_run=True,
            message="Dry-run: patch not written (set enable=True or AUTODEV_ENABLE_PATCH_APPLY=1).",
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(patch.updated, encoding="utf-8")
    return PatchResult(
        path=patch.path,
        applied=True,
        dry_run=False,
        message=f"Patch applied to {target}.",
    )


__all__ = ["generate_patch", "apply_patch"]
