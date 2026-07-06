"""Reference deterministic skill: apply a unified diff with path-guard/dry-run.

Wraps :mod:`backend.patches.engine` rather than reimplementing path-traversal
guarding or dry-run gating.
"""

from __future__ import annotations

from typing import Any

from backend.patches.engine import apply_patch, generate_patch


def run(
    path: str,
    original: str,
    updated: str,
    root: str = ".",
    enable: bool = False,
) -> dict[str, Any]:
    """Generate and (optionally) apply a patch for a single file.

    Args:
        path: Logical file path, relative to ``root``.
        original: Original file content.
        updated: New file content.
        root: Filesystem root the write is guarded against escaping.
        enable: ``True`` to actually write; ``False`` (default) dry-runs.

    Returns:
        A dict with ``applied``, ``dryRun``, and ``message``.
    """
    patch = generate_patch(path, original, updated)
    result = apply_patch(patch, root=root, enable=enable)
    return {"applied": result.applied, "dryRun": result.dry_run, "message": result.message}


def register() -> None:
    """Plugin entrypoint hook; this skill has no extra registration side effects."""
    return None


__all__ = ["register", "run"]
