"""CLI plugin for the patch engine — U13.

Registers two subcommands via the ``backend.cli_plugins`` auto-loader:

* ``autodev patches generate --path P [--original-file F1] [--updated-file F2]``
  Print the unified diff between the original and updated file contents.

* ``autodev patches apply --path P [--original-file F1] [--updated-file F2]``
  ``[--root R] [--enable]``
  Apply the patch. Dry-run by default; writes only when ``--enable`` is passed
  or the environment variable ``AUTODEV_ENABLE_PATCH_APPLY=1`` is set.

The ``backend.patches`` package is imported lazily so that an ``ImportError``
produces a clean error message rather than a startup crash. No edits to
``backend.cli`` are required — the auto-loader handles registration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _read(path: str | None) -> str:
    """Return the text content of *path*, or an empty string when not given."""
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8")


def _handle_patches_generate(args: argparse.Namespace) -> int:
    """Generate a unified diff and print it to stdout."""
    try:
        from backend.patches import generate_patch  # noqa: PLC0415
    except ImportError:
        print(json.dumps({"error": "patches subsystem unavailable"}), file=sys.stderr)
        return 1

    patch = generate_patch(args.path, _read(args.original_file), _read(args.updated_file))
    print(patch.diff if patch.diff else "(no changes)")
    return 0


def _handle_patches_apply(args: argparse.Namespace) -> int:
    """Apply a patch (dry-run unless enabled); print the result as JSON."""
    try:
        from backend.patches import apply_patch, generate_patch  # noqa: PLC0415
    except ImportError:
        print(json.dumps({"error": "patches subsystem unavailable"}), file=sys.stderr)
        return 1

    patch = generate_patch(args.path, _read(args.original_file), _read(args.updated_file))
    result = apply_patch(patch, root=args.root, enable=True if args.enable else None)
    print(
        json.dumps(
            {
                "path": result.path,
                "applied": result.applied,
                "dry_run": result.dry_run,
                "message": result.message,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def register(subparsers: Any) -> None:
    """Add the ``patches`` sub-tree to the CLI argument parser.

    Called automatically by ``backend.cli_plugins.register_subcommands()``.
    """
    patches_parser = subparsers.add_parser("patches", help="Generate and apply patches")
    patches_subparsers = patches_parser.add_subparsers(dest="patches_command", required=True)

    generate_parser = patches_subparsers.add_parser("generate", help="Generate a unified diff")
    generate_parser.add_argument("--path", required=True, help="Logical file path used in the diff header")
    generate_parser.add_argument("--original-file", dest="original_file", help="Path to the original content file")
    generate_parser.add_argument("--updated-file", dest="updated_file", help="Path to the updated content file")
    generate_parser.set_defaults(handler=_handle_patches_generate)

    apply_parser = patches_subparsers.add_parser(
        "apply",
        help="Apply a patch (dry-run unless --enable or AUTODEV_ENABLE_PATCH_APPLY=1)",
    )
    apply_parser.add_argument("--path", required=True, help="Target file path relative to --root")
    apply_parser.add_argument("--original-file", dest="original_file", help="Path to the original content file")
    apply_parser.add_argument("--updated-file", dest="updated_file", help="Path to the updated content file")
    apply_parser.add_argument("--root", default=".", help="Filesystem root the target must reside under")
    apply_parser.add_argument("--enable", action="store_true", help="Actually write the file (override dry-run)")
    apply_parser.set_defaults(handler=_handle_patches_apply)
