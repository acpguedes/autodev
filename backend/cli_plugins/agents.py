"""CLI plugin for the agents registry — U6.

Registers one subcommand via the ``backend.cli_plugins`` auto-loader:

* ``autodev agents list``
  Print a JSON array with every known agent (defaults + registry-discovered),
  including the ``name``, ``source``, and ``has_metadata_contract`` fields.

No edits to ``backend.cli`` are required — the auto-loader handles
registration automatically.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

# The 8 default agents always listed regardless of import success.
_DEFAULT_AGENT_NAMES: list[str] = [
    "planner",
    "navigator",
    "analyzer",
    "architect",
    "coder",
    "devops",
    "validator",
    "responder",
]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_agents_list(args: argparse.Namespace) -> int:  # noqa: ARG001
    """Print all known agents as a JSON array."""
    agents: dict[str, dict[str, Any]] = {}

    # 1. Seed with defaults.
    try:
        from backend.agents.contracts import AGENT_METADATA_MODELS  # noqa: PLC0415
    except ImportError:
        AGENT_METADATA_MODELS = {}

    for name in _DEFAULT_AGENT_NAMES:
        agents[name] = {
            "name": name,
            "source": "default",
            "has_metadata_contract": name in AGENT_METADATA_MODELS,
        }

    # 2. Merge registry-discovered agents.
    # Explicitly import specialized modules so their self-registration fires.
    _SPECIALIZED = [
        "backend.agents.security",
        "backend.agents.refactor",
        "backend.agents.docs",
    ]
    for _mod in _SPECIALIZED:
        try:
            import importlib as _il  # noqa: PLC0415
            _il.import_module(_mod)
        except Exception:
            logger.debug("Could not import specialized agent module %r", _mod)

    try:
        from backend.agents.registry import discover_agents  # noqa: PLC0415
        discovered = discover_agents()
        for reg_name, instance in discovered.items():
            has_contract = False
            try:
                model = instance.metadata_model()
                has_contract = model is not None
            except Exception:
                pass
            if reg_name not in agents:
                agents[reg_name] = {
                    "name": reg_name,
                    "source": "registry",
                    "has_metadata_contract": has_contract,
                }
    except Exception:
        logger.debug("Could not discover registry agents", exc_info=True)

    output = sorted(agents.values(), key=lambda a: a["name"])
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(subparsers: Any) -> None:
    """Add ``agents`` sub-tree to the CLI argument parser."""
    agents_parser = subparsers.add_parser("agents", help="Inspect registered agents")
    agents_subparsers = agents_parser.add_subparsers(dest="agents_command", required=True)

    list_parser = agents_subparsers.add_parser("list", help="List all known agents")
    list_parser.set_defaults(handler=_handle_agents_list)
