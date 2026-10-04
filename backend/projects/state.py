"""Deterministic project-state probe (E63-S2).

A pure filesystem inspection of a project root -- no LLM, no network, no
database -- producing a small typed snapshot the flow selector and the router
use as ground truth about the project (empty vs populated, Git, tests,
languages). The snapshot never carries file contents or the root path.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import threading

from backend.routing.contract import ContextDigest, ContextSignals

#: Directories never descended into (mirrors ``backend.repository.indexing``).
IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".next",
    }
)

#: Upper bound on entries visited per probe, keeping per-turn cost bounded.
MAX_VISITED_ENTRIES = 5000

_LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".kt": "kotlin",
    ".swift": "swift",
}


@dataclass(frozen=True)
class ProjectState:
    """Typed snapshot of a project root's real state.

    Attributes:
        populated: Whether the root holds any content besides ignored entries
            (a lone ``.git`` directory still counts as empty).
        git: Whether the root is a Git repository.
        tests: Whether a test suite is present.
        languages: Sorted languages detected from source file extensions.
    """

    populated: bool = False
    git: bool = False
    tests: bool = False
    languages: tuple[str, ...] = ()

    def to_context_digest(self, repo: str = "") -> ContextDigest:
        """Project the snapshot onto the E5 routing contract.

        Args:
            repo: Opaque repository identifier (never a filesystem path).

        Returns:
            A :class:`ContextDigest` carrying ``has_tests`` and ``languages``.
        """
        return ContextDigest(
            repo=repo,
            signals=ContextSignals(has_tests=self.tests, languages=self.languages),
        )


def _is_test_entry(name: str, is_dir: bool) -> bool:
    """Whether a file/directory name denotes a test suite."""
    lowered = name.lower()
    if is_dir:
        return lowered in {"tests", "test", "__tests__", "spec"}
    return (
        lowered.startswith("test_")
        or lowered.endswith(("_test.py", "_test.go", ".test.ts", ".test.tsx", ".test.js", ".spec.ts", ".spec.js"))
    )


def probe_project_state(root: str | Path) -> ProjectState:
    """Inspect *root* and return its :class:`ProjectState`.

    Ignored directories are pruned during traversal and never entered; the
    walk stops after :data:`MAX_VISITED_ENTRIES` entries.

    Args:
        root: Project root directory. A missing path yields an empty state.

    Returns:
        The probed snapshot.
    """
    base = Path(root)
    if not base.is_dir():
        return ProjectState()
    git = (base / ".git").exists()
    populated = False
    tests = False
    languages: set[str] = set()
    visited = 0
    for _dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRECTORIES)
        if any(_is_test_entry(d, True) for d in dirnames):
            tests = True
        for name in filenames:
            populated = True
            if _is_test_entry(name, False):
                tests = True
            language = _LANGUAGE_BY_SUFFIX.get(Path(name).suffix.lower())
            if language:
                languages.add(language)
        if dirnames:
            populated = True
        visited += len(dirnames) + len(filenames)
        if visited >= MAX_VISITED_ENTRIES:
            break
    return ProjectState(
        populated=populated,
        git=git,
        tests=tests,
        languages=tuple(sorted(languages)),
    )


_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, ProjectState]] = {}


def _root_stamp(base: Path) -> float:
    """Cheap change token: newest mtime of the root and its direct entries."""
    try:
        stamps = [base.stat().st_mtime]
        with os.scandir(base) as entries:
            for entry in entries:
                if entry.name in IGNORED_DIRECTORIES and entry.name != ".git":
                    continue
                stamps.append(entry.stat().st_mtime)
        return max(stamps)
    except OSError:
        return 0.0


def cached_project_state(root: str | Path) -> ProjectState:
    """Return the probed state, cached per root until the root changes.

    Invalidation compares the newest mtime of the root and its direct
    entries, so adding/removing top-level files or directories re-probes.

    Args:
        root: Project root directory.

    Returns:
        The (possibly cached) snapshot.
    """
    base = Path(root).resolve()
    key = str(base)
    stamp = _root_stamp(base)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    state = probe_project_state(base)
    with _CACHE_LOCK:
        _CACHE[key] = (stamp, state)
    return state


def clear_state_cache() -> None:
    """Drop every cached snapshot (used by tests)."""
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = [
    "IGNORED_DIRECTORIES",
    "ProjectState",
    "cached_project_state",
    "clear_state_cache",
    "probe_project_state",
]
