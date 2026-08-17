"""Tests for the retrieval recall/latency benchmark (E7-S2/E7-S3 DoD).

The benchmark's aggregation is deliberately independent of PostgreSQL so the
metric definitions -- which is what a gate reads -- are pinned by tests that
run in the default offline suite. Producing real numbers still needs a live
pgvector instance; that path is covered by ``scripts/benchmark_retrieval.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.repository.retrieval.benchmark import (
    BenchmarkReport,
    ModeMetrics,
    RetrievalCase,
    percentile,
    recall_at_k,
    reciprocal_rank,
    run_benchmark,
)
from backend.repository.retrieval.retriever import Snippet

from scripts.benchmark_retrieval import check_thresholds, load_cases


def _snippet(chunk_id: int) -> Snippet:
    """Build a snippet carrying only the id the benchmark reads.

    Args:
        chunk_id: Identifier assigned to the snippet.

    Returns:
        A snippet with placeholder content.
    """
    return Snippet(
        chunk_id=chunk_id,
        file_path="pkg/mod.py",
        symbol="fn",
        start_line=0,
        end_line=1,
        content="body",
        score=1.0,
        source="hybrid",
    )


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------


def test_recall_at_k_counts_only_hits_within_the_cut_off() -> None:
    """A relevant chunk ranked past k does not count towards recall."""
    assert recall_at_k([1, 2, 3, 4], {1, 4}, 2) == 0.5
    assert recall_at_k([1, 2, 3, 4], {1, 4}, 4) == 1.0
    assert recall_at_k([9], {1}, 10) == 0.0


def test_recall_at_k_is_one_when_nothing_is_labeled_relevant() -> None:
    """An unlabeled case cannot be missed, so it must not depress the mean."""
    assert recall_at_k([1, 2], set(), 10) == 1.0


def test_reciprocal_rank_uses_the_first_relevant_position() -> None:
    """MRR is driven by the first hit, not by how many hits follow."""
    assert reciprocal_rank([5, 7, 3], {3, 7}) == pytest.approx(0.5)
    assert reciprocal_rank([3], {3}) == 1.0
    assert reciprocal_rank([1, 2], {9}) == 0.0


def test_percentile_uses_nearest_rank_so_results_are_observed_values() -> None:
    """A reported percentile is always a measurement, never an interpolation."""
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 0.5) == 20.0
    assert percentile(values, 0.95) == 40.0
    assert percentile(values, 1.0) == 40.0
    assert percentile([], 0.95) == 0.0


def test_percentile_rejects_a_fraction_outside_the_unit_interval() -> None:
    """A percentile above 1.0 is a caller bug, not a clamp."""
    with pytest.raises(ValueError):
        percentile([1.0], 1.5)


# ---------------------------------------------------------------------------
# Benchmark run
# ---------------------------------------------------------------------------


def test_run_benchmark_aggregates_recall_and_latency_per_mode() -> None:
    """Each mode is measured independently over the same labeled cases."""
    elapsed = iter([0.0, 0.010, 0.0, 0.030] * 4)

    def fake_retrieve(conn: Any, query: str, **kwargs: Any) -> list[Snippet]:
        """Return a perfect result set for hybrid and a miss for lexical.

        Args:
            conn: Unused.
            query: Unused.
            **kwargs: Carries the ``mode`` under measurement.

        Returns:
            Snippets whose ids decide the case's recall.
        """
        return [_snippet(1)] if kwargs["mode"] == "hybrid" else [_snippet(99)]

    cases = [
        RetrievalCase(query="a", relevant_chunk_ids=frozenset({1})),
        RetrievalCase(query="b", relevant_chunk_ids=frozenset({1})),
    ]

    report = run_benchmark(
        conn=None,
        cases=cases,
        tenant_id="tenant",
        modes=("lexical", "hybrid"),
        k=5,
        retrieve_fn=fake_retrieve,
        clock=lambda: next(elapsed),
    )

    assert report.k == 5
    by_mode = {metrics.mode: metrics for metrics in report.modes}
    assert by_mode["lexical"].recall_at_k == 0.0
    assert by_mode["lexical"].mean_reciprocal_rank == 0.0
    assert by_mode["hybrid"].recall_at_k == 1.0
    assert by_mode["hybrid"].mean_reciprocal_rank == 1.0
    assert by_mode["hybrid"].case_count == 2
    # 10 ms then 30 ms, so nearest-rank p50 is the lower observation.
    assert by_mode["lexical"].latency_p50_ms == pytest.approx(10.0)
    assert by_mode["lexical"].latency_p95_ms == pytest.approx(30.0)


def test_run_benchmark_counts_a_failing_case_instead_of_aborting() -> None:
    """One backend failure must not destroy the whole measurement."""

    def flaky_retrieve(conn: Any, query: str, **kwargs: Any) -> list[Snippet]:
        """Fail for one query and succeed for the other.

        Args:
            conn: Unused.
            query: Decides whether this call raises.
            **kwargs: Unused.

        Returns:
            A perfect result set for the non-failing query.

        Raises:
            RuntimeError: For the query labeled ``"boom"``.
        """
        if query == "boom":
            raise RuntimeError("connection reset")
        return [_snippet(1)]

    report = run_benchmark(
        conn=None,
        cases=[
            RetrievalCase(query="boom", relevant_chunk_ids=frozenset({1})),
            RetrievalCase(query="ok", relevant_chunk_ids=frozenset({1})),
        ],
        tenant_id="tenant",
        modes=("hybrid",),
        retrieve_fn=flaky_retrieve,
    )

    hybrid = report.modes[0]
    assert hybrid.error_count == 1
    assert hybrid.case_count == 2
    assert hybrid.recall_at_k == 0.5


def test_report_serializes_to_a_stable_json_shape() -> None:
    """The report is attachable as DoD evidence without post-processing."""
    report = BenchmarkReport(
        k=10,
        modes=(
            ModeMetrics(
                mode="hybrid",
                case_count=3,
                recall_at_k=0.9,
                mean_reciprocal_rank=0.8,
                latency_p50_ms=42.0,
                latency_p95_ms=180.0,
                error_count=0,
            ),
        ),
    )

    payload = report.to_dict()

    assert payload["k"] == 10
    assert payload["modes"][0]["latencyP95Ms"] == 180.0
    assert json.loads(json.dumps(payload)) == payload


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def test_load_cases_parses_labeled_queries(tmp_path: Path) -> None:
    """The CLI case file maps to typed benchmark cases."""
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps([{"query": "how is retry configured", "relevantChunkIds": [3, 7]}]),
        encoding="utf-8",
    )

    cases = load_cases(path)

    assert cases == [
        RetrievalCase(query="how is retry configured", relevant_chunk_ids=frozenset({3, 7}))
    ]


def test_load_cases_rejects_a_case_without_a_query(tmp_path: Path) -> None:
    """A malformed label set must fail loudly rather than measure nothing."""
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{"relevantChunkIds": [1]}]), encoding="utf-8")

    with pytest.raises(ValueError, match="case 0 has no 'query'"):
        load_cases(path)


def test_check_thresholds_reports_beta_gate_violations() -> None:
    """The p95 and recall thresholds are what make this runnable as a gate."""
    report = BenchmarkReport(
        k=10,
        modes=(
            ModeMetrics(
                mode="hybrid",
                case_count=1,
                recall_at_k=0.4,
                mean_reciprocal_rank=0.4,
                latency_p50_ms=100.0,
                latency_p95_ms=420.0,
                error_count=0,
            ),
        ),
    )

    violations = check_thresholds(report, max_p95_ms=300.0, min_recall=0.7)

    assert len(violations) == 2
    assert "420.0 ms exceeds 300.0 ms" in violations[0]
    assert "below 0.700" in violations[1]
    assert check_thresholds(report, max_p95_ms=None, min_recall=None) == []
