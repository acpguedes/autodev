"""Governed interactive shell (``autodev --shell``, E14-S6).

Talks **only** to the Control Plane API (``/v2``) over HTTP — this module
never imports ``backend.orchestrator``, ``backend.execution``,
``backend.persistence``, or any other ``backend.*`` module (API-first,
v2 platform reference §2.13). Enforced by a static-analysis contract test:
``backend/tests/unit/cli/test_cli_shell_api_only.py``.

Flow: prompt for a goal -> ``POST /v2/sessions`` -> ``POST
.../turns`` (drives the agent pipeline that derives the execution plan) ->
``POST .../execution-plan/execute?mode=<mode>`` -> condensed per-task
summary. If
the run comes back ``awaiting_approval`` (E14-S3), the pending decision is
shown inline and the operator's answer resolves it via ``POST
/v2/execution/decisions/{id}/resolve``, then the run is continued via
``POST .../execution-plan/resume``. Supports all three modes
(auto/approval/hybrid) via ``--mode``.

Scope note: this module does not stream ``execution.action.*`` SSE events
live — the synchronous execute/resume response already carries every
task's result (including diffs/stdout, in ``results[].metadata.actions``),
which is enough for a condensed post-hoc summary without holding an
indefinitely-open stream connection open past run completion. Real-time
streaming for the *shell* is a candidate follow-up now that the Web UX
(E14-S5) has already built and proven the SSE consumption pattern.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Sequence, TextIO

import httpx

_DEFAULT_BASE_URL = "http://127.0.0.1:8000"
_MODES = ("auto", "approval", "hybrid")


def build_shell_parser() -> argparse.ArgumentParser:
    """Build the ``autodev --shell`` argument parser.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(prog="autodev --shell", add_help=True)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AUTODEV_SHELL_BASE_URL", _DEFAULT_BASE_URL),
        help="Control Plane API base URL (default: %(default)s, or AUTODEV_SHELL_BASE_URL).",
    )
    parser.add_argument(
        "--mode",
        choices=_MODES,
        default="auto",
        help="Execution mode: auto (default), approval, or hybrid.",
    )
    parser.add_argument(
        "--command",
        default=None,
        help="Run one goal non-interactively and exit, instead of starting the REPL.",
    )
    return parser


class ShellSession:
    """Thin HTTP client over ``/v2`` for one shell session's lifetime."""

    def __init__(self, client: httpx.Client, mode: str) -> None:
        """Initialize the session.

        Args:
            client: An ``httpx.Client`` already bound to the API base URL.
            mode: Active execution mode (``"auto"``/``"approval"``/``"hybrid"``).
        """
        self._client = client
        self.mode = mode

    def create_session(self, goal: str) -> str:
        """Create a new session for *goal* and return its id."""
        response = self._client.post("/v2/sessions", json={"goal": goal})
        response.raise_for_status()
        return str(response.json()["session_id"])

    def create_turn(self, session_id: str, message: str) -> dict[str, Any]:
        """Post a message, driving the session's agent pipeline (planner/analyzer/.../validator).

        Required before :meth:`execute`: the execution plan is derived from
        artifacts this pipeline produces, not from session creation alone.
        """
        response = self._client.post(f"/v2/sessions/{session_id}/turns", json={"message": message})
        response.raise_for_status()
        return dict(response.json())

    def execute(self, session_id: str) -> dict[str, Any]:
        """Execute the session's derived plan under the active mode."""
        response = self._client.post(
            f"/v2/sessions/{session_id}/execution-plan/execute", params={"mode": self.mode}
        )
        response.raise_for_status()
        return dict(response.json())

    def resume(self, session_id: str, run_id: str) -> dict[str, Any]:
        """Resume a paused run under the active mode."""
        response = self._client.post(
            f"/v2/sessions/{session_id}/execution-plan/resume",
            params={"run_id": run_id, "mode": self.mode},
        )
        response.raise_for_status()
        return dict(response.json())

    def list_pending_decisions(self) -> list[dict[str, Any]]:
        """List the caller's tenant's still-pending execution-action decisions."""
        response = self._client.get("/v2/execution/decisions")
        response.raise_for_status()
        return list(response.json()["decisions"])

    def resolve_decision(self, decision_id: str, decision: str, persist_as_rule: bool = False) -> dict[str, Any]:
        """Approve or deny one pending decision."""
        response = self._client.post(
            f"/v2/execution/decisions/{decision_id}/resolve",
            json={"decision": decision, "persistAsRule": persist_as_rule},
        )
        response.raise_for_status()
        return dict(response.json())


def _print_run_summary(run: dict[str, Any], *, out: TextIO) -> None:
    """Print one condensed line per step, including any actions' diff/stdout excerpt."""
    for step in run.get("steps", []):
        print(f"  [{step['status']}] {step['step_key']}", file=out)
    for result in run.get("results", []):
        actions = result.get("metadata", {}).get("actions", [])
        for action in actions:
            if action.get("diff"):
                first_line = action["diff"].splitlines()[0] if action["diff"].splitlines() else ""
                print(f"    diff: {first_line}", file=out)
            if action.get("error"):
                print(f"    error: {action['error']}", file=out)


def _handle_pending_decision(
    session: ShellSession, session_id: str, run: dict[str, Any], *, out: TextIO, prompt_fn: Any
) -> dict[str, Any]:
    """Show the run's pending decision inline, resolve it, and resume the run."""
    decisions = session.list_pending_decisions()
    matching = [d for d in decisions if d["runId"] == run["run_id"]]
    if not matching:
        print("  (awaiting a decision not visible to this tenant yet — stopping)", file=out)
        return run
    decision = matching[0]
    print(f"  pending: {decision['prompt']} (category={decision['category']})", file=out)
    answer = prompt_fn("  approve / approve-always / deny > ").strip().lower()
    if answer in ("a", "approve"):
        session.resolve_decision(decision["decisionId"], "approve", False)
    elif answer in ("always", "approve-always"):
        session.resolve_decision(decision["decisionId"], "approve", True)
    else:
        session.resolve_decision(decision["decisionId"], "deny", False)
    resumed = session.resume(session_id, run["run_id"])
    _print_run_summary(resumed, out=out)
    return resumed


def run_goal(session: ShellSession, goal: str, *, out: TextIO = sys.stdout, prompt_fn: Any = input) -> dict[str, Any]:
    """Run one goal to completion: create a session, execute, resolve any pauses.

    Args:
        session: The active shell session.
        goal: The goal to run.
        out: Stream to print progress to.
        prompt_fn: Callable used for the inline decision prompt (injectable for tests).

    Returns:
        The final run document.
    """
    session_id = session.create_session(goal)
    print(f"session: {session_id}", file=out)
    session.create_turn(session_id, goal)
    run = session.execute(session_id)
    _print_run_summary(run, out=out)
    while run["status"] == "awaiting_approval":
        previous_run_id = run["run_id"]
        run = _handle_pending_decision(session, session_id, run, out=out, prompt_fn=prompt_fn)
        if run["run_id"] == previous_run_id and run["status"] == "awaiting_approval":
            # No visible decision to resolve; avoid spinning forever.
            break
    print(f"final status: {run['status']}", file=out)
    return run


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``autodev --shell``.

    Args:
        argv: Argument vector to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = build_shell_parser()
    args = parser.parse_args(argv)

    with httpx.Client(base_url=args.base_url, timeout=120.0) as client:
        session = ShellSession(client, args.mode)

        if args.command:
            try:
                run_goal(session, args.command)
            except httpx.HTTPError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            return 0

        print(f"autodev shell (mode={args.mode}). Type a goal, or 'exit' to quit.")
        while True:
            try:
                goal = input("goal> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not goal:
                continue
            if goal.lower() in ("exit", "quit"):
                return 0
            try:
                run_goal(session, goal)
            except httpx.HTTPError as exc:
                print(f"error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
