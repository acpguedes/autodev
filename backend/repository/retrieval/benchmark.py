"""Retrieval recall/latency benchmark (E7-S2/E7-S3 DoD).

E7 shipped hybrid retrieval without the recall/latency benchmark both stories
declared in their Definition of Done, and the v2.0-beta wave gate carries a
CNF ("Hybrid retrieval reaches p95 < 300 ms and the recall baseline") that has
no harness behind it. This module is that harness.

The measurement logic here is pure and dependency-free so it is unit-testable
without PostgreSQL; :func:`run_benchmark` takes the retrieval callable as an
argument, and ``scripts/benchmark_retrieval.py`` is the thin CLI that binds it
to a live psycopg connection. Producing the gate numbers therefore still
requires a PostgreSQL instance with ``pgvector`` and an indexed corpus -- what
this module removes is the absence of a defined, reproducible measurement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from backend.repository.retrieval.retriever import RetrievalMode, Snippet

#: Modes measured when a caller does not narrow the set.
DEFAULT_MODES: tuple[RetrievalMode, ...] = ("lexical", "vector", "hybrid")

#: Default cut-off for recall@k.
DEFAULT_K = 10


#: Retrieval entry point under measurement. Called as
#: ``fn(conn, query, tenant_id=..., mode=..., limit=...)``; kept as a loose
#: ``Callable`` so both the real retriever and a test double satisfy it
#: without either having to mirror the other's exact keyword signature.
RetrieveCallable = Callable[..., list[Snippet]]


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    """One labeled benchmark query.

    Attributes:
        query: The query text issued to the retriever.
        relevant_chunk_ids: Ids of the ``code_chunks`` rows a correct result
            set should surface. Recall is measured against this label set, so
            it must be curated per corpus rather than derived from the
            retriever's own output.
    """

    query: str
    relevant_chunk_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class ModeMetrics:
    """Aggregated metrics for one retrieval mode.

    Attributes:
        mode: The measured retrieval mode.
        case_count: Number of labeled cases executed.
        recall_at_k: Mean fraction of each case's relevant chunks found within
            the top *k* results.
        mean_reciprocal_rank: Mean of ``1 / rank`` of each case's first
            relevant hit (``0.0`` for a case with no hit).
        latency_p50_ms: Median per-query wall-clock latency.
        latency_p95_ms: 95th-percentile per-query wall-clock latency -- the
            figure the v2.0-beta gate's ``p95 < 300 ms`` CNF is read from.
        error_count: Cases whose retrieval call raised; they contribute
            ``0.0`` recall and are excluded from the latency percentiles.
    """

    mode: str
    case_count: int
    recall_at_k: float
    mean_reciprocal_rank: float
    latency_p50_ms: float
    latency_p95_ms: float
    error_count: int


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Full benchmark result across every measured mode.

    Attributes:
        k: Cut-off used for recall@k.
        modes: Per-mode metrics, in the order they were measured.
    """

    k: int
    modes: tuple[ModeMetrics, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the report.

        Returns:
            A mapping with the cut-off and one entry per measured mode,
            suitable for attaching to a story's DoD evidence or feeding the
            Evaluation Service.
        """
        return {
            "k": self.k,
            "modes": [
                {
                    "mode": metrics.mode,
                    "caseCount": metrics.case_count,
                    "recallAtK": metrics.recall_at_k,
                    "meanReciprocalRank": metrics.mean_reciprocal_rank,
                    "latencyP50Ms": metrics.latency_p50_ms,
                    "latencyP95Ms": metrics.latency_p95_ms,
                    "errorCount": metrics.error_count,
                }
                for metrics in self.modes
            ],
        }


def recall_at_k(
    retrieved_chunk_ids: Sequence[int],
    relevant_chunk_ids: Iterable[int],
    k: int,
) -> float:
    """Return the fraction of relevant chunks present in the top *k* results.

    Args:
        retrieved_chunk_ids: Chunk ids in retrieval order.
        relevant_chunk_ids: Labeled relevant chunk ids for this query.
        k: Cut-off applied to *retrieved_chunk_ids*.

    Returns:
        A value in ``[0.0, 1.0]``; ``1.0`` when the case labels no relevant
        chunk, since there is nothing the retriever could have missed.
    """
    relevant = set(relevant_chunk_ids)
    if not relevant:
        return 1.0
    top_k = set(retrieved_chunk_ids[:k])
    return len(top_k & relevant) / len(relevant)


def reciprocal_rank(
    retrieved_chunk_ids: Sequence[int],
    relevant_chunk_ids: Iterable[int],
) -> float:
    """Return ``1 / rank`` of the first relevant result, or ``0.0`` if absent.

    Args:
        retrieved_chunk_ids: Chunk ids in retrieval order.
        relevant_chunk_ids: Labeled relevant chunk ids for this query.

    Returns:
        The reciprocal of the 1-based rank of the first relevant hit.
    """
    relevant = set(relevant_chunk_ids)
    for position, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if chunk_id in relevant:
            return 1.0 / position
    return 0.0


def percentile(values: Sequence[float], fraction: float) -> float:
    """Return the *fraction* percentile of *values* by nearest-rank.

    Nearest-rank is used rather than interpolation so a reported p95 is always
    an observed measurement, which is what a latency gate should be read from.

    Args:
        values: Measurements; need not be sorted.
        fraction: Percentile as a fraction in ``[0.0, 1.0]``, e.g. ``0.95``.

    Returns:
        The selected measurement, or ``0.0`` when *values* is empty.

    Raises:
        ValueError: If *fraction* is outside ``[0.0, 1.0]``.
    """
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"fraction must be within [0.0, 1.0], got {fraction!r}")
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(-(-fraction * len(ordered) // 1)) - 1))
    return ordered[index]


def run_benchmark(
    conn: Any,
    cases: Sequence[RetrievalCase],
    *,
    tenant_id: str,
    modes: Sequence[RetrievalMode] = DEFAULT_MODES,
    k: int = DEFAULT_K,
    retrieve_fn: RetrieveCallable | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> BenchmarkReport:
    """Measure recall and latency for every mode over the labeled *cases*.

    A retrieval call that raises is counted as a zero-recall case rather than
    aborting the run: a benchmark that dies on the first backend hiccup
    produces no evidence at all, which is the situation this harness exists to
    fix. Failures are reported via :attr:`ModeMetrics.error_count`.

    Args:
        conn: Connection handed to *retrieve_fn* unchanged.
        cases: Labeled queries to execute.
        tenant_id: Tenant to scope every query to.
        modes: Retrieval modes to measure.
        k: Cut-off for recall@k; also the ``limit`` requested per query.
        retrieve_fn: Retrieval entry point; defaults to
            :func:`backend.repository.retrieval.retriever.retrieve`. Injected
            so the aggregation logic is testable without PostgreSQL.
        clock: Monotonic clock used for latency, injectable for deterministic
            tests.

    Returns:
        The aggregated report across every measured mode.
    """
    if retrieve_fn is None:
        from backend.repository.retrieval.retriever import retrieve as default_retrieve

        active_retrieve: RetrieveCallable = default_retrieve
    else:
        active_retrieve = retrieve_fn

    measured: list[ModeMetrics] = []
    for mode in modes:
        recalls: list[float] = []
        ranks: list[float] = []
        latencies: list[float] = []
        errors = 0

        for case in cases:
            started = clock()
            try:
                snippets = active_retrieve(
                    conn,
                    case.query,
                    tenant_id=tenant_id,
                    mode=mode,
                    limit=k,
                )
            except Exception:  # noqa: BLE001 - a failing case must not end the run
                errors += 1
                recalls.append(0.0)
                ranks.append(0.0)
                continue
            latencies.append((clock() - started) * 1000.0)
            retrieved = [snippet.chunk_id for snippet in snippets]
            recalls.append(recall_at_k(retrieved, case.relevant_chunk_ids, k))
            ranks.append(reciprocal_rank(retrieved, case.relevant_chunk_ids))

        measured.append(
            ModeMetrics(
                mode=mode,
                case_count=len(cases),
                recall_at_k=_mean(recalls),
                mean_reciprocal_rank=_mean(ranks),
                latency_p50_ms=percentile(latencies, 0.5),
                latency_p95_ms=percentile(latencies, 0.95),
                error_count=errors,
            )
        )

    return BenchmarkReport(k=k, modes=tuple(measured))


def _mean(values: Sequence[float]) -> float:
    """Return the arithmetic mean of *values*, or ``0.0`` when empty.

    Args:
        values: Measurements to average.

    Returns:
        The mean value.
    """
    return sum(values) / len(values) if values else 0.0


__all__ = [
    "DEFAULT_K",
    "DEFAULT_MODES",
    "BenchmarkReport",
    "ModeMetrics",
    "RetrievalCase",
    "RetrieveCallable",
    "percentile",
    "recall_at_k",
    "reciprocal_rank",
    "run_benchmark",
]
