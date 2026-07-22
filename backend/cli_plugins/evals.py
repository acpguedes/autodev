"""CLI plugin for on-demand/CI eval triggers (E12-S3).

Registers ``autodev eval run <eval.yaml>`` via the ``backend.cli_plugins``
auto-loader. The command loads and validates an ``eval.yaml`` spec, resolves
its dataset into :class:`~backend.evals.contract.EvalCase` objects via
:mod:`backend.evals.dataset_loader`, runs it offline through
:meth:`backend.evals.service.EvaluationService.run_offline` (which persists
the immutable :class:`~backend.evals.results.EvalResult` via the configured
:func:`backend.persistence.database.get_store`), prints the result as JSON,
and exits non-zero when the spec's quality gate fails (or the run itself
fails) — this is what makes it usable as a CI gate
(``.github/workflows/ci-evals.yml``) and as the ``make eval-reference``
target.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _handle_eval_run(args: argparse.Namespace) -> int:
    """Handle ``autodev eval run``: run an eval spec offline and gate on it.

    Args:
        args: Parsed CLI arguments — ``spec_path``, optional ``dataset``
            override, and optional ``run_id``.

    Returns:
        ``0`` when the run succeeds and its gate passes, ``1`` when the run
        succeeds but the gate fails, ``2`` on a spec/dataset loading error.
    """
    from backend.evals.contract import EvalError
    from backend.evals.dataset_loader import EvalDatasetError, load_eval_cases, resolve_dataset_path
    from backend.evals.service import EvaluationService
    from backend.evals.spec import load_eval_spec
    from backend.persistence.database import get_store

    spec_path = Path(args.spec_path)
    try:
        spec = load_eval_spec(spec_path)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": f"failed to load eval spec {spec_path}: {exc}"}), file=sys.stderr)
        return 2

    if spec.mode != "offline":
        print(
            json.dumps({"error": f"autodev eval run only supports mode='offline', got {spec.mode!r}"}),
            file=sys.stderr,
        )
        return 2

    dataset_path = Path(args.dataset) if args.dataset else resolve_dataset_path(spec_path, spec.dataset.ref)
    try:
        cases = load_eval_cases(dataset_path)
    except EvalDatasetError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    service = EvaluationService(get_store())
    try:
        result = service.run_offline(spec, cases, run_id=args.run_id)
    except EvalError as exc:
        print(json.dumps({"error": f"eval run failed: {exc}"}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "evalId": result.eval_id,
                "evalVersion": result.eval_version,
                "runId": result.run_id,
                "agentId": result.agent_id,
                "datasetSize": result.dataset_size,
                "gatePassed": result.gate_passed,
                "gateReason": result.gate_reason,
                "metrics": result.metrics.to_document(),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if result.gate_passed else 1


def register(subparsers: Any) -> None:
    """Add the ``eval`` sub-tree to the CLI argument parser.

    Args:
        subparsers: The object returned by
            :meth:`argparse.ArgumentParser.add_subparsers` on the top-level
            ``autodev`` parser.
    """
    eval_parser = subparsers.add_parser("eval", help="Run evaluation specs")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)

    run_parser = eval_subparsers.add_parser(
        "run",
        help="Run an eval.yaml spec offline, persist the result, and gate on it",
    )
    run_parser.add_argument("spec_path", help="Path to the eval.yaml spec file")
    run_parser.add_argument(
        "--dataset",
        default=None,
        help="Dataset file path override (defaults to dataset.ref resolved relative to the spec file)",
    )
    run_parser.add_argument("--run-id", default=None, help="Explicit run id (defaults to a fresh UUID4)")
    run_parser.set_defaults(handler=_handle_eval_run)


__all__ = ["register"]
