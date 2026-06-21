"""Router auto-include loader.

Iterates every ``*.py`` module in this package (excluding ``__init__.py`` and
private/dunder files), imports each via :mod:`importlib`, and registers it
against the supplied FastAPI application.

Two registration conventions are supported:

* A module-level ``router`` attribute that is a :class:`fastapi.APIRouter`
  instance — registered via ``app.include_router(module.router)``.
* A module-level ``attach(app)`` callable — called with the application
  instance (useful for middleware or lifespan hooks that cannot be expressed as
  a plain router).

Import or registration errors for any individual module are caught and logged;
they never prevent other routers from loading or crash app startup.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def include_all_routers(app: "FastAPI") -> None:
    """Register every router module found in this package against *app*.

    Safe to call when the package directory contains only ``__init__.py`` —
    results in a no-op without side effects.
    """
    package_dir = Path(__file__).parent

    for module_info in pkgutil.iter_modules([str(package_dir)]):
        module_name = module_info.name
        if module_name.startswith("_"):
            continue

        full_name = f"{__name__.rsplit('.', 1)[0]}.routers.{module_name}"
        try:
            module = importlib.import_module(full_name)
        except Exception:
            logger.exception("Failed to import router module %r — skipping", full_name)
            continue

        try:
            router = getattr(module, "router", None)
            if router is not None:
                app.include_router(router)
                logger.debug("Included router from %r", full_name)
        except Exception:
            logger.exception("Failed to include router from %r — skipping", full_name)

        try:
            attach = getattr(module, "attach", None)
            if callable(attach):
                attach(app)
                logger.debug("Called attach() from %r", full_name)
        except Exception:
            logger.exception("Failed to call attach() from %r — skipping", full_name)


__all__ = ["include_all_routers"]
