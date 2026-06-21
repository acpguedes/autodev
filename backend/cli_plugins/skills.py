"""CLI plugin for the skills subsystem — U4.

Registers two subcommands via the ``backend.cli_plugins`` auto-loader:

* ``autodev skills list``
  Print a JSON array of ``{name, description}`` for every registered skill.

* ``autodev skills invoke <name> [--input key=value ...]``
  Invoke a skill by name with the supplied key=value pairs; print the
  :class:`SkillResult` fields as JSON.

The ``backend.skills`` package is imported lazily so that an ``ImportError``
produces a clean error message rather than a startup crash.

No edits to ``backend.cli`` are required — the auto-loader handles
registration automatically.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_skills_list(args: argparse.Namespace) -> int:  # noqa: ARG001
    """Print all registered skills as a JSON array."""
    try:
        from backend.skills import discover_skills  # noqa: PLC0415
    except ImportError:
        print(json.dumps({"error": "skills subsystem unavailable"}), file=sys.stderr)
        return 1

    registry = discover_skills()
    output = [
        {"name": name, "description": getattr(instance, "description", "") or ""}
        for name, instance in sorted(registry.items())
    ]
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


def _handle_skills_invoke(args: argparse.Namespace) -> int:
    """Invoke a skill by name; print the result as JSON."""
    try:
        from backend.skills import SkillContext, invoke_skill  # noqa: PLC0415
    except ImportError:
        print(json.dumps({"error": "skills subsystem unavailable"}), file=sys.stderr)
        return 1

    # Parse --input key=value pairs into a dict.
    inputs: dict[str, Any] = {}
    for pair in args.input or []:
        if "=" not in pair:
            print(
                json.dumps({"error": f"Invalid --input format (expected key=value): {pair!r}"}),
                file=sys.stderr,
            )
            return 1
        key, _, value = pair.partition("=")
        inputs[key.strip()] = value

    try:
        ctx = SkillContext(inputs=inputs)
        result = invoke_skill(args.skill_name, ctx)
    except KeyError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "content": result.content,
                "data": result.data,
                "success": result.success,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(subparsers: Any) -> None:
    """Add ``skills`` sub-tree to the CLI argument parser.

    Called automatically by ``backend.cli_plugins.register_subcommands()``.
    """
    skills_parser = subparsers.add_parser("skills", help="Manage and invoke skills")
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command", required=True)

    # --- skills list ---
    list_parser = skills_subparsers.add_parser("list", help="List all registered skills")
    list_parser.set_defaults(handler=_handle_skills_list)

    # --- skills invoke ---
    invoke_parser = skills_subparsers.add_parser("invoke", help="Invoke a skill by name")
    invoke_parser.add_argument("skill_name", help="Name of the skill to invoke")
    invoke_parser.add_argument(
        "--input",
        metavar="KEY=VALUE",
        action="append",
        help="Input key=value pair (may be repeated)",
    )
    invoke_parser.set_defaults(handler=_handle_skills_invoke)
