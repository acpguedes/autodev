"""Immutable, versioned eval run results (E5-S3).

An eval run produces an :class:`EvalResult`: the aggregated per-evaluator
scores, the computed quality/cost/latency metrics, and the quality-gate
outcome. Results are never overwritten (see ADR-009) — each run is stored
under its own ``(eval_id, eval_version, run_id)`` key so history stays
queryable and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.evals.contract import EvalCaseScore

#: Schema version stamped on every persisted :class:`EvalResult` document.
EVAL_RESULT_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class EvaluatorResult:
    """Aggregated result of one evaluator across an entire run.

    Attributes:
        evaluator_id: Identifier of the evaluator.
        kind: Evaluator kind (``"deterministic"``, ``"llm-as-judge"``, or custom).
        mean_score: Mean of the evaluator's per-case scores, in ``[0, 1]``.
        case_scores: Per-case scores, in dataset order.
    """

    evaluator_id: str
    kind: str
    mean_score: float
    case_scores: tuple[EvalCaseScore, ...] = ()

    def to_document(self) -> dict[str, Any]:
        """Render this result as a JSON-serializable document."""
        return {
            "evaluatorId": self.evaluator_id,
            "kind": self.kind,
            "meanScore": self.mean_score,
            "caseScores": [case_score.to_document() for case_score in self.case_scores],
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "EvaluatorResult":
        """Parse a result back from its JSON document.

        Args:
            document: Document produced by :meth:`to_document`.

        Returns:
            The reconstructed :class:`EvaluatorResult`.
        """
        return cls(
            evaluator_id=str(document["evaluatorId"]),
            kind=str(document["kind"]),
            mean_score=float(document["meanScore"]),
            case_scores=tuple(
                EvalCaseScore.from_document(case_score) for case_score in document.get("caseScores", [])
            ),
        )


@dataclass(frozen=True)
class RunMetrics:
    """Computed quality/cost/latency metrics for one run.

    Attributes:
        quality: Mean score per evaluator id, in ``[0, 1]``.
        cost_usd_mean: Mean per-case cost in USD.
        cost_usd_p95: p95 per-case cost in USD.
        latency_p50_seconds: Median per-case latency in seconds.
        latency_p95_seconds: p95 per-case latency in seconds.
    """

    quality: dict[str, float] = field(default_factory=dict)
    cost_usd_mean: float = 0.0
    cost_usd_p95: float = 0.0
    latency_p50_seconds: float = 0.0
    latency_p95_seconds: float = 0.0

    def to_document(self) -> dict[str, Any]:
        """Render these metrics as a JSON-serializable document."""
        return {
            "quality": self.quality,
            "cost": {"usdMean": self.cost_usd_mean, "usdP95": self.cost_usd_p95},
            "latency": {"p50Seconds": self.latency_p50_seconds, "p95Seconds": self.latency_p95_seconds},
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "RunMetrics":
        """Parse metrics back from their JSON document.

        Args:
            document: Document produced by :meth:`to_document`.

        Returns:
            The reconstructed :class:`RunMetrics`.
        """
        cost = document.get("cost") or {}
        latency = document.get("latency") or {}
        return cls(
            quality=dict(document.get("quality") or {}),
            cost_usd_mean=float(cost.get("usdMean", 0.0)),
            cost_usd_p95=float(cost.get("usdP95", 0.0)),
            latency_p50_seconds=float(latency.get("p50Seconds", 0.0)),
            latency_p95_seconds=float(latency.get("p95Seconds", 0.0)),
        )


@dataclass(frozen=True)
class EvalResult:
    """Immutable, versioned outcome of one eval run — the persisted record.

    Every run produces a new :class:`EvalResult`, keyed by
    ``(eval_id, eval_version, run_id)``; results are never overwritten (see
    ADR-009), so history stays queryable and reproducible.

    Attributes:
        eval_id: Id of the eval spec that produced this result.
        eval_version: Version of the eval spec that produced this result.
        run_id: Unique identifier of this specific run.
        mode: ``"offline"`` or ``"online"``.
        dataset_ref: Dataset reference the run scored.
        dataset_split: Dataset split the run scored.
        dataset_size: Number of cases actually scored in this run.
        evaluator_results: Per-evaluator aggregated results.
        metrics: Computed quality/cost/latency metrics.
        gate_passed: Whether the spec's quality gate passed (``True`` when no
            gate is declared).
        gate_reason: Human-readable explanation of the gate outcome.
        created_at: ISO-8601 UTC timestamp the result was produced.
    """

    eval_id: str
    eval_version: str
    run_id: str
    mode: str
    dataset_ref: str
    dataset_split: str
    dataset_size: int
    evaluator_results: tuple[EvaluatorResult, ...]
    metrics: RunMetrics
    gate_passed: bool
    gate_reason: str
    created_at: str

    def to_document(self) -> dict[str, Any]:
        """Render this result as a JSON-serializable API/storage document."""
        return {
            "schemaVersion": EVAL_RESULT_SCHEMA_VERSION,
            "evalId": self.eval_id,
            "evalVersion": self.eval_version,
            "runId": self.run_id,
            "mode": self.mode,
            "dataset": {"ref": self.dataset_ref, "split": self.dataset_split, "size": self.dataset_size},
            "evaluators": [result.to_document() for result in self.evaluator_results],
            "metrics": self.metrics.to_document(),
            "gate": {"passed": self.gate_passed, "reason": self.gate_reason},
            "createdAt": self.created_at,
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "EvalResult":
        """Parse a result back from its JSON document.

        Args:
            document: Document produced by :meth:`to_document`.

        Returns:
            The reconstructed :class:`EvalResult`.
        """
        dataset = document.get("dataset") or {}
        gate = document.get("gate") or {}
        return cls(
            eval_id=str(document["evalId"]),
            eval_version=str(document["evalVersion"]),
            run_id=str(document["runId"]),
            mode=str(document.get("mode", "offline")),
            dataset_ref=str(dataset.get("ref", "")),
            dataset_split=str(dataset.get("split", "")),
            dataset_size=int(dataset.get("size", 0)),
            evaluator_results=tuple(
                EvaluatorResult.from_document(result) for result in document.get("evaluators", [])
            ),
            metrics=RunMetrics.from_document(document.get("metrics") or {}),
            gate_passed=bool(gate.get("passed", True)),
            gate_reason=str(gate.get("reason", "")),
            created_at=str(document.get("createdAt", "")),
        )


__all__ = ["EVAL_RESULT_SCHEMA_VERSION", "EvalResult", "EvaluatorResult", "RunMetrics"]
