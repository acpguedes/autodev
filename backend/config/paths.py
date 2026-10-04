"""Global, source-tree-independent path resolution (E61-S1).

Owns every filesystem path that belongs to the *tool* itself rather than to
one project: the global home directory and everything resolved under it.
Every function here is pure path arithmetic -- no I/O beyond an explicit
``mkdir`` when a caller asks for one via :func:`ensure_autodev_home` -- so
resolution is testable under ``monkeypatch.chdir``/``monkeypatch.setenv``
without touching a real home directory.

Nothing in this module is computed from ``__file__``: every path here must
resolve identically whether the code runs from a repository checkout or from
a wheel installed into an unrelated virtualenv (ADR-015).
"""

from __future__ import annotations

import os
from pathlib import Path

#: Directory name used under the user's home directory when ``AUTODEV_HOME``
#: is not set.
DEFAULT_HOME_DIR_NAME = ".autodev"

#: Filename shared by both the global and the per-project configuration
#: layers (E61-S2) -- only the directory they resolve against differs.
CONFIG_FILE_NAME = "autodev.config.json"

#: Directory, under the global home, holding the tool's own data (the
#: default state database and anything else global-but-not-configuration).
GLOBAL_DATA_DIR_NAME = "data"

#: Filename of the default SQLite state database under the global data dir.
STATE_DB_FILE_NAME = "autodev.db"


def autodev_home() -> Path:
    """Resolve the tool's global home directory.

    ``AUTODEV_HOME`` wins when set (expanded, not created); otherwise
    ``~/.autodev``.

    Returns:
        The global home directory path. Not guaranteed to exist -- call
        :func:`ensure_autodev_home` when the caller needs it created.
    """
    configured = os.getenv("AUTODEV_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / DEFAULT_HOME_DIR_NAME


def global_config_path() -> Path:
    """Resolve the global configuration file path, under the global home.

    Returns:
        ``<autodev_home()>/autodev.config.json``.
    """
    return autodev_home() / CONFIG_FILE_NAME


def global_data_dir() -> Path:
    """Resolve the global data directory, under the global home.

    Returns:
        ``<autodev_home()>/data``.
    """
    return autodev_home() / GLOBAL_DATA_DIR_NAME


def global_state_db_path() -> Path:
    """Resolve the default state database file path, under the global data dir.

    Returns:
        ``<autodev_home()>/data/autodev.db``. An explicitly configured
        ``DATABASE_URL`` always wins over this default (unchanged by E61).
    """
    return global_data_dir() / STATE_DB_FILE_NAME


def ensure_autodev_home() -> Path:
    """Create the global home directory (and its data subdirectory) if missing.

    The only function in this module that performs I/O; callers that just
    need to resolve a path use the functions above instead.

    Returns:
        The global home directory path, guaranteed to exist on return.
    """
    home = autodev_home()
    global_data_dir().mkdir(parents=True, exist_ok=True)
    return home


__all__ = [
    "CONFIG_FILE_NAME",
    "DEFAULT_HOME_DIR_NAME",
    "GLOBAL_DATA_DIR_NAME",
    "STATE_DB_FILE_NAME",
    "autodev_home",
    "ensure_autodev_home",
    "global_config_path",
    "global_data_dir",
    "global_state_db_path",
]
