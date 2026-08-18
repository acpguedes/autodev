"""Versioned build metadata for ``autodev --version`` (E34-S1-T2).

Resolves the installed package version, a best-effort source revision, and
a build date so the CLI can report what is actually running without
requiring a repo checkout to be present (an installed wheel/sdist has no
``.git`` directory).
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

_PACKAGE_NAME = "autodev-backend"
_FALLBACK_VERSION = "0.0.0+unknown"


@dataclass(frozen=True)
class VersionInfo:
    """Build metadata reported by ``autodev --version``.

    Attributes:
        version: Installed package version, from package metadata
            (``importlib.metadata``). Falls back to a sentinel when the
            package was not installed through packaging metadata at all
            (e.g. running straight from a checkout with no ``pip install``).
        commit: Short git commit hash the running code was checked out at,
            or ``"unknown"`` when no repository is available (a packaged
            install with no ``.git`` directory) and no
            ``AUTODEV_BUILD_COMMIT`` override was baked in at build time.
        build_date: ISO-8601 build date, sourced from ``AUTODEV_BUILD_DATE``
            (set by the packaging step that produced the artifact), or
            ``"unknown"`` for a plain source install where no packaging step
            set it.
    """

    version: str
    commit: str
    build_date: str

    def as_dict(self) -> dict[str, str]:
        """Return this metadata as a JSON-serializable dict."""
        return {"version": self.version, "commit": self.commit, "build_date": self.build_date}


def _resolve_version() -> str:
    """Return the installed ``autodev-backend`` package version, or a fallback sentinel."""
    try:
        return importlib.metadata.version(_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return _FALLBACK_VERSION


def _resolve_commit() -> str:
    """Return the short git commit hash, an explicit override, or ``"unknown"``."""
    override = os.environ.get("AUTODEV_BUILD_COMMIT", "").strip()
    if override:
        return override
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=Path(__file__).resolve().parent,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _resolve_build_date() -> str:
    """Return the packaging-time build date, or ``"unknown"`` when unset."""
    return os.environ.get("AUTODEV_BUILD_DATE", "").strip() or "unknown"


def get_version_info() -> VersionInfo:
    """Return the current process's version/commit/build-date metadata.

    Returns:
        A :class:`VersionInfo` resolved fresh on every call (no caching, so
        it always reflects the current environment/overrides).
    """
    return VersionInfo(
        version=_resolve_version(),
        commit=_resolve_commit(),
        build_date=_resolve_build_date(),
    )


__all__ = ["VersionInfo", "get_version_info"]
