"""CLI plugin for projects (E62-S4-T2).

``autodev project list|open|init|create`` mirrors ``/v2/projects`` over HTTP --
the CLI is a ``/v2`` client like every other, so it never touches the State
Store. ``open`` without a path walks up from the current directory to the
nearest ``.autodev/`` (E62-S1), which is how running ``autodev`` from a
subdirectory finds its project.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _base_url(args: argparse.Namespace) -> str:
    return args.base_url or os.environ.get("AUTODEV_SHELL_BASE_URL", "http://127.0.0.1:8000")


def _call(args: argparse.Namespace, method: str, path: str, body: dict[str, Any] | None = None) -> int:
    import httpx

    with httpx.Client(base_url=_base_url(args), timeout=30.0) as client:
        response = client.request(method, path, json=body)
    if response.status_code >= 400:
        detail = response.json().get("error", {}).get("message") if response.headers.get(
            "content-type", ""
        ).startswith("application/json") else response.text
        print(f"error: {detail or response.text}", file=sys.stderr)
        return 1
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    return 0


def _handle_list(args: argparse.Namespace) -> int:
    return _call(args, "GET", "/v2/projects")


def _handle_open(args: argparse.Namespace) -> int:
    root = args.root
    if root is None:
        from backend.projects.discovery import discover_project_root

        found = discover_project_root(Path.cwd())
        if found is None:
            print(
                "error: no .autodev/ found here or in any parent directory; "
                "use `autodev project init` or `autodev project create`",
                file=sys.stderr,
            )
            return 1
        root = str(found)
    return _call(args, "POST", "/v2/projects/open", {"root": str(Path(root).expanduser().resolve())})


def _handle_init(args: argparse.Namespace) -> int:
    body: dict[str, Any] = {"root": str(Path(args.root).expanduser().resolve())}
    if args.name:
        body["name"] = args.name
    return _call(args, "POST", "/v2/projects/init", body)


def _handle_create(args: argparse.Namespace) -> int:
    body: dict[str, Any] = {"root": str(Path(args.root).expanduser().resolve())}
    if args.name:
        body["name"] = args.name
    return _call(args, "POST", "/v2/projects/create", body)


def register(subparsers: Any) -> None:
    """Register ``autodev project`` and its four subcommands."""
    project = subparsers.add_parser("project", help="Manage projects (E62)")
    sub = project.add_subparsers(dest="project_command", required=True)

    def _add(name: str, help_: str, handler: Any) -> argparse.ArgumentParser:
        parser = sub.add_parser(name, help=help_)
        parser.add_argument("--base-url", default=None)
        parser.set_defaults(handler=handler)
        return parser

    _add("list", "List projects and show the active one", _handle_list)
    open_parser = _add("open", "Open an existing project (default: nearest .autodev/ above here)", _handle_open)
    open_parser.add_argument("root", nargs="?", default=None)
    init_parser = _add("init", "Configure an existing directory as a project, leaving its files untouched", _handle_init)
    init_parser.add_argument("root", nargs="?", default=".")
    init_parser.add_argument("--name", default=None)
    create_parser = _add("create", "Create a new directory and initialize it as a project", _handle_create)
    create_parser.add_argument("root")
    create_parser.add_argument("--name", default=None)
