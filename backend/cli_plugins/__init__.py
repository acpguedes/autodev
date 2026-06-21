"""CLI subcommand auto-loader.

Iterates every ``*.py`` module in this package (excluding ``__init__.py`` and
private/dunder files) and calls its ``register(subparsers)`` function if
present.  This lets new CLI subcommands be added by dropping a single module
into this directory — no edits to :mod:`backend.cli` are needed.

Import or registration errors for any individual module are caught and logged;
they never cause the existing CLI to fail.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def register_subcommands(subparsers: Any) -> None:
    """Discover and register CLI subcommands from plugin modules.

    *subparsers* is the object returned by
    :meth:`argparse.ArgumentParser.add_subparsers`.

    Safe to call when the package directory contains only ``__init__.py`` —
    results in a no-op without side effects.
    """
    package_dir = Path(__file__).parent

    for module_info in pkgutil.iter_modules([str(package_dir)]):
        module_name = module_info.name
        if module_name.startswith("_"):
            continue

        full_name = f"backend.cli_plugins.{module_name}"
        try:
            module = importlib.import_module(full_name)
        except Exception:
            logger.exception("Failed to import CLI plugin module %r — skipping", full_name)
            continue

        try:
            register_fn = getattr(module, "register", None)
            if callable(register_fn):
                register_fn(subparsers)
                logger.debug("Registered CLI subcommands from %r", full_name)
        except Exception:
            logger.exception("Failed to call register() from CLI plugin %r — skipping", full_name)


__all__ = ["register_subcommands"]
