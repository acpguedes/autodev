"""CLI plugin for the plans subsystem — U11.

Registers subcommands via the ``backend.cli_plugins`` auto-loader:

* ``autodev plans show <session_id>``
  Print the plan document (steps, status, updated_at) as JSON.

* ``autodev plans approve <session_id> --actor <name> [--note <text>]``
  Approve the plan; print the updated document as JSON.

* ``autodev plans reject <session_id> --actor <name> [--note <text>]``
  Reject the plan; print the updated document as JSON.

``backend.plans`` is imported lazily so a missing package produces a clean
error message rather than a startup crash.

No edits to ``backend.cli`` are required — the auto-loader handles
registration via ``register(subparsers)`` automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_store() -> Any:
    """Return a ``PlanStore`` instance or print an error and return None."""
    try:
        from backend.plans import PlanStore  # noqa: PLC0415
    except ImportError as exc:
        print(f"error: plans subsystem unavailable: {exc}", file=sys.stderr)
        return None

    db_url = os.environ.get("DATABASE_URL", "")
    db_path: Path | None = None
    if db_url.startswith("sqlite:///"):
        raw = db_url.removeprefix("sqlite:///")
        db_path = Path(raw).expanduser().resolve()

    return PlanStore(db_path=db_path)


def _plan_to_dict(plan: Any) -> dict:
    return {
        "session_id": plan.session_id,
        "steps": plan.steps,
        "status": plan.status,
        "updated_at": plan.updated_at,
    }


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_show(args: argparse.Namespace) -> int:
    store = _make_store()
    if store is None:
        return 1

    plan = store.get_plan(args.session_id)
    if plan is None:
        print(
            f"error: no plan found for session {args.session_id!r}", file=sys.stderr
        )
        return 1

    print(json.dumps(_plan_to_dict(plan), indent=2))
    return 0


def _handle_approve(args: argparse.Namespace) -> int:
    store = _make_store()
    if store is None:
        return 1

    plan = store.get_plan(args.session_id)
    if plan is None:
        print(
            f"error: no plan found for session {args.session_id!r}", file=sys.stderr
        )
        return 1

    store.approve(args.session_id, actor=args.actor, note=args.note or "")
    updated = store.get_plan(args.session_id)
    print(json.dumps(_plan_to_dict(updated), indent=2))
    return 0


def _handle_reject(args: argparse.Namespace) -> int:
    store = _make_store()
    if store is None:
        return 1

    plan = store.get_plan(args.session_id)
    if plan is None:
        print(
            f"error: no plan found for session {args.session_id!r}", file=sys.stderr
        )
        return 1

    store.reject(args.session_id, actor=args.actor, note=args.note or "")
    updated = store.get_plan(args.session_id)
    print(json.dumps(_plan_to_dict(updated), indent=2))
    return 0


# ---------------------------------------------------------------------------
# Auto-loader registration
# ---------------------------------------------------------------------------


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the ``plans`` subcommand group with *subparsers*."""
    plans_parser = subparsers.add_parser(
        "plans", help="Manage persisted approvable plans."
    )
    plans_sub = plans_parser.add_subparsers(dest="plans_subcommand")
    plans_sub.required = True

    # ---- show ---------------------------------------------------------------
    show_parser = plans_sub.add_parser(
        "show", help="Display the plan for a session."
    )
    show_parser.add_argument("session_id", help="Session identifier.")
    show_parser.set_defaults(handler=_handle_show)

    # ---- approve ------------------------------------------------------------
    approve_parser = plans_sub.add_parser(
        "approve", help="Approve the plan for a session."
    )
    approve_parser.add_argument("session_id", help="Session identifier.")
    approve_parser.add_argument(
        "--actor", required=True, help="Name of the approver."
    )
    approve_parser.add_argument("--note", default="", help="Optional note.")
    approve_parser.set_defaults(handler=_handle_approve)

    # ---- reject -------------------------------------------------------------
    reject_parser = plans_sub.add_parser(
        "reject", help="Reject the plan for a session."
    )
    reject_parser.add_argument("session_id", help="Session identifier.")
    reject_parser.add_argument(
        "--actor", required=True, help="Name of the rejector."
    )
    reject_parser.add_argument("--note", default="", help="Optional note.")
    reject_parser.set_defaults(handler=_handle_reject)
