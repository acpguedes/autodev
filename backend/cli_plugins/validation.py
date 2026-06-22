"""CLI plugin for the validation sandbox — U15.

Registers ``autodev validate run -- <command...>`` via the
``backend.cli_plugins`` auto-loader. Execution is DISABLED by default; set
``AUTODEV_ENABLE_SANDBOX`` to actually run commands. ``backend.validation`` is
imported lazily so an ``ImportError`` yields a clean error message.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any


def _handle_validate_run(args: argparse.Namespace) -> int:
    """Run a validation command through the sandbox; print the result as JSON."""
    try:
        from backend.validation import SandboxRunner, ValidationJob  # noqa: PLC0415
    except ImportError:
        print(json.dumps({"error": "validation subsystem unavailable"}), file=sys.stderr)
        return 1

    command = list(args.command or [])
    # Strip a leading "--" separator if the user wrote `validate run -- cmd ...`.
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print(json.dumps({"error": "no command provided"}), file=sys.stderr)
        return 1

    job = ValidationJob(job_id=str(uuid.uuid4()), command=command, cwd=args.cwd)
    result = SandboxRunner().run(job)
    print(
        json.dumps(
            {
                "job_id": result.job_id,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "backend": result.backend,
                "skipped": result.skipped,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def register(subparsers: Any) -> None:
    """Add the ``validate`` sub-tree to the CLI argument parser."""
    validate_parser = subparsers.add_parser("validate", help="Run validation commands in the sandbox")
    validate_subparsers = validate_parser.add_subparsers(dest="validate_command", required=True)

    run_parser = validate_subparsers.add_parser(
        "run",
        help="Run a command (skipped unless AUTODEV_ENABLE_SANDBOX is set)",
    )
    run_parser.add_argument("--cwd", default=".", help="Working directory for the command")
    run_parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run, e.g. -- pytest -q",
    )
    run_parser.set_defaults(handler=_handle_validate_run)
