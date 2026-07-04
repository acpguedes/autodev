"""SDK command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from backend.sdk.scaffold import scaffold_plugin


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sdk", description="AutoDev plugin SDK tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="Create new SDK projects")
    new_subparsers = new_parser.add_subparsers(dest="kind", required=True)
    plugin_parser = new_subparsers.add_parser("plugin", help="Scaffold a plugin project")
    plugin_parser.add_argument("plugin_id", help="Plugin id in namespace/name kebab-case format")
    plugin_parser.add_argument("--output", type=Path, required=True, help="Directory to create")
    plugin_parser.set_defaults(handler=_handle_new_plugin)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns structured errors
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1


def _handle_new_plugin(args: argparse.Namespace) -> int:
    path = scaffold_plugin(args.plugin_id, args.output)
    print(json.dumps({"status": "ok", "path": str(path)}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
