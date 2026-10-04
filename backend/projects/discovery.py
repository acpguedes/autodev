"""Ancestor-walking project discovery (E62-S1-T1).

Pure path traversal: no network, no database, no LLM.
"""

from __future__ import annotations

from pathlib import Path

from backend.projects.models import PROJECT_DIR_NAME


def find_project_marker(start: Path) -> tuple[Path, int] | None:
    """Find the nearest ancestor of *start* containing ``.autodev/``.

    Args:
        start: Directory to start from (itself included).

    Returns:
        ``(project_root, depth)`` where ``depth`` is how many levels above
        *start* the marker was found (0 = *start* itself), or ``None`` when no
        ancestor has one. A directory the caller cannot read is skipped as a
        candidate but the walk continues upward.
    """
    current = start.resolve()
    depth = 0
    while True:
        try:
            if (current / PROJECT_DIR_NAME).is_dir():
                return current, depth
        except OSError:
            pass
        if current.parent == current:
            return None
        current = current.parent
        depth += 1


def discover_project_root(start: Path) -> Path | None:
    """Return the nearest project root at or above *start*, or ``None``.

    Args:
        start: Directory to start from.

    Returns:
        The nearest directory containing ``.autodev/``; nested projects resolve
        to the innermost one.
    """
    found = find_project_marker(start)
    return found[0] if found else None
