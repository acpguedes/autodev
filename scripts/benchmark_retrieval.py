#!/usr/bin/env python3
"""Retrieval recall/latency benchmark CLI (E7-S2/E7-S3 DoD evidence).

Runs a labeled query set through
:func:`backend.repository.retrieval.retriever.retrieve` in each mode and prints
a JSON report with recall@k, MRR, and p50/p95 latency -- the numbers E7-S2 and
E7-S3 declared in their DoD and the figure the v2.0-beta gate CNF ("Hybrid
retrieval reaches p95 < 300 ms and the recall baseline") is read from.

This needs a live PostgreSQL with ``pgvector`` and an indexed corpus; it cannot
run offline, which is precisely why E7 closed without the numbers. Usage::

    python scripts/benchmark_retrieval.py --cases evals/retrieval/cases.json \\
        --database-url postgresql://autodev:autodev@localhost:5432/autodev

The cases file is a JSON list of ``{"query": str, "relevantChunkIds": [int]}``.
Label it against the corpus you indexed -- recall is only meaningful relative
to a curated ground truth, so a generated label set would measure nothing.

Exits non-zero when a ``--max-p95-ms`` / ``--min-recall`` threshold is given
and the hybrid mode misses it, so the benchmark can gate a release.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

# Allow `python scripts/benchmark_retrieval.py` from a checkout without install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.persistence.tenancy import DEFAULT_TENANT_ID  # noqa: E402
from backend.repository.retrieval.benchmark import (  # noqa: E402
    DEFAULT_K,
    DEFAULT_MODES,
    BenchmarkReport,
    RetrievalCase,
    run_benchmark,
)


def load_cases(path: Path) -> list[RetrievalCase]:
    """Load labeled benchmark cases from a JSON file.

    Args:
        path: Path to a JSON list of ``{"query", "relevantChunkIds"}`` objects.

    Returns:
        The parsed cases.

    Raises:
        ValueError: If the document is not a list, or an entry is missing
            ``query``.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, list):
        raise ValueError(f"{path}: expected a JSON list of cases")
    cases: list[RetrievalCase] = []
    for index, entry in enumerate(document):
        if not isinstance(entry, dict) or "query" not in entry:
            raise ValueError(f"{path}: case {index} has no 'query'")
        cases.append(
            RetrievalCase(
                query=str(entry["query"]),
                relevant_chunk_ids=frozenset(
                    int(chunk_id) for chunk_id in entry.get("relevantChunkIds", ())
                ),
            )
        )
    return cases


def open_connection(database_url: str) -> Any:
    """Open a psycopg connection for the benchmark.

    Args:
        database_url: PostgreSQL connection URL.

    Returns:
        An open psycopg connection.

    Raises:
        RuntimeError: If ``psycopg`` is not installed.
    """
    try:
        import psycopg  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised when optional dep missing
        raise RuntimeError(
            "psycopg is required to benchmark retrieval. Install backend requirements."
        ) from exc
    return psycopg.connect(database_url)


def check_thresholds(
    report: BenchmarkReport,
    *,
    max_p95_ms: float | None,
    min_recall: float | None,
) -> list[str]:
    """Return the threshold violations for the hybrid mode.

    Args:
        report: Benchmark report to check.
        max_p95_ms: Maximum acceptable p95 latency, or ``None`` to skip.
        min_recall: Minimum acceptable recall@k, or ``None`` to skip.

    Returns:
        Human-readable violation messages; empty when every threshold holds or
        the hybrid mode was not measured.
    """
    hybrid = next((metrics for metrics in report.modes if metrics.mode == "hybrid"), None)
    if hybrid is None:
        return []
    violations: list[str] = []
    if max_p95_ms is not None and hybrid.latency_p95_ms > max_p95_ms:
        violations.append(
            f"hybrid p95 {hybrid.latency_p95_ms:.1f} ms exceeds {max_p95_ms:.1f} ms"
        )
    if min_recall is not None and hybrid.recall_at_k < min_recall:
        violations.append(
            f"hybrid recall@{report.k} {hybrid.recall_at_k:.3f} below {min_recall:.3f}"
        )
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark and print its JSON report.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` on success, ``1`` when a configured threshold is violated.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, required=True, help="Labeled cases JSON file")
    parser.add_argument(
        "--database-url",
        required=True,
        help="PostgreSQL URL of a database with an indexed corpus and pgvector",
    )
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID, help="Tenant to scope queries to")
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="Cut-off for recall@k")
    parser.add_argument(
        "--modes",
        nargs="+",
        default=list(DEFAULT_MODES),
        choices=list(DEFAULT_MODES),
        help="Retrieval modes to measure",
    )
    parser.add_argument("--max-p95-ms", type=float, default=None, help="Fail above this p95")
    parser.add_argument("--min-recall", type=float, default=None, help="Fail below this recall@k")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    if not cases:
        print(f"{args.cases}: no cases to run", file=sys.stderr)
        return 1

    connection = open_connection(args.database_url)
    try:
        report = run_benchmark(
            connection,
            cases,
            tenant_id=args.tenant_id,
            modes=tuple(args.modes),
            k=args.k,
        )
    finally:
        connection.close()

    print(json.dumps(report.to_dict(), indent=2))

    violations = check_thresholds(
        report, max_p95_ms=args.max_p95_ms, min_recall=args.min_recall
    )
    for violation in violations:
        print(f"threshold violated: {violation}", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
