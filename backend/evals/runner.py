"""Offline eval execution (E5-S3).

:class:`EvalRunner` executes every evaluator declared in an
:class:`~backend.evals.contract.EvalSpec` over a sequence of
:class:`~backend.evals.contract.EvalCase` objects, aggregates per-evaluator
scores, computes quality/cost/latency metrics, and evaluates the spec's
quality gate. Two built-in evaluator kinds ship out of the box —
``deterministic`` (a safe boolean expression checked against the case
payload) and ``llm-as-judge`` (a rubric scored by an :class:`LLMProvider`) —
and callers may register additional kinds without touching this module,
satisfying the "pluggable Evaluator" functional DoD.
"""

from __future__ import annotations

import json
import statistics
from typing import Any, Mapping, Sequence

from backend.agents.provider import LLMProvider, StubLLMProvider
from backend.evals.contract import (
    EvalCase,
    EvalCaseScore,
    EvalError,
    EvaluatorNotFoundError,
    EvaluatorSpec,
    EvalSpec,
    GateSpec,
    RubricCriterion,
)
from backend.evals.expressions import ExpressionError, evaluate_expression
from backend.evals.results import EvaluatorResult, RunMetrics


class DeterministicEvaluator:
    """Scores a case by evaluating :attr:`EvaluatorSpec.check` against its payload."""

    def score(self, spec: EvaluatorSpec, case: EvalCase, provider: LLMProvider) -> EvalCaseScore:
        """Evaluate the deterministic check expression against the case payload.

        Args:
            spec: Evaluator spec; ``check`` must be set.
            case: The case to score.
            provider: Unused by this evaluator.

        Returns:
            A score of ``1.0`` when the check is true, ``0.0`` otherwise, or
            ``0.0`` with an ``error`` detail when the check cannot be evaluated
            (fails soft so one bad case does not abort the whole run).
        """
        del provider
        if not spec.check:
            return EvalCaseScore(
                case_id=case.case_id,
                evaluator_id=spec.id,
                score=0.0,
                details={"error": "evaluator has no 'check' expression"},
            )
        try:
            passed = evaluate_expression(spec.check, case.payload)
        except ExpressionError as exc:
            return EvalCaseScore(
                case_id=case.case_id,
                evaluator_id=spec.id,
                score=0.0,
                details={"check": spec.check, "error": str(exc)},
            )
        return EvalCaseScore(
            case_id=case.case_id,
            evaluator_id=spec.id,
            score=1.0 if passed else 0.0,
            details={"check": spec.check, "passed": passed},
        )


class LLMJudgeEvaluator:
    """Scores a case by prompting an :class:`LLMProvider` against a rubric.

    The provider is expected to return a JSON object mapping each rubric
    criterion name to a numeric value within its declared scale; the final
    score is the rubric's weighted, scale-normalized average. A criterion
    missing from the response, or a response that is not valid JSON, scores
    ``0.0`` for that criterion (fail soft) with the issue recorded in
    ``details`` — this keeps one malformed judge response from aborting the
    whole run.
    """

    def score(self, spec: EvaluatorSpec, case: EvalCase, provider: LLMProvider) -> EvalCaseScore:
        """Prompt the judge and compute the rubric-weighted score.

        Args:
            spec: Evaluator spec; ``rubric`` must be a non-empty mapping.
            case: The case to score; ``payload["candidate"]`` (falling back to
                the full payload) is the text/content presented to the judge.
            provider: LLM provider invoked to obtain rubric scores.

        Returns:
            The rubric-weighted score in ``[0, 1]``, with the raw judge
            response and per-criterion breakdown in ``details``.
        """
        if not spec.rubric:
            return EvalCaseScore(
                case_id=case.case_id,
                evaluator_id=spec.id,
                score=0.0,
                details={"error": "evaluator has no rubric"},
            )
        candidate = case.payload.get("candidate", case.payload)
        prompt = _render_judge_prompt(spec, candidate)
        response = provider.complete(
            prompt,
            agent_id=f"eval-judge:{spec.id}",
            run_id=case.case_id,
            tenant_id="eval",
        )
        try:
            judged = json.loads(response.text)
            if not isinstance(judged, dict):
                raise ValueError("judge response must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            return EvalCaseScore(
                case_id=case.case_id,
                evaluator_id=spec.id,
                score=0.0,
                details={"error": f"invalid judge response: {exc}", "raw": response.text},
            )
        breakdown: dict[str, float] = {}
        total_weight = 0.0
        weighted_sum = 0.0
        for name, criterion in spec.rubric.items():
            raw_value = judged.get(name)
            normalized = _normalize(raw_value, criterion)
            breakdown[name] = normalized
            weighted_sum += normalized * criterion.weight
            total_weight += criterion.weight
        score = weighted_sum / total_weight if total_weight > 0 else 0.0
        return EvalCaseScore(
            case_id=case.case_id,
            evaluator_id=spec.id,
            score=max(0.0, min(1.0, score)),
            details={"breakdown": breakdown, "raw": judged},
        )


def _render_judge_prompt(spec: EvaluatorSpec, candidate: Any) -> str:
    """Build the prompt sent to the judge model for one case.

    Args:
        spec: Evaluator spec carrying the rubric and (recorded) judge model.
        candidate: The candidate content to be judged.

    Returns:
        A prompt instructing the judge to return one JSON object mapping each
        rubric criterion name to a numeric value within its declared scale.
    """
    criteria_lines = "\n".join(
        f"- {name}: scale {criterion.scale[0]}-{criterion.scale[1]}, weight {criterion.weight}"
        for name, criterion in spec.rubric.items()
    )
    return (
        f"You are judge model {spec.model or 'unspecified'} scoring a candidate "
        f"against the following rubric:\n{criteria_lines}\n\n"
        f"Candidate:\n{candidate}\n\n"
        "Respond with a single JSON object mapping each criterion name to a "
        "numeric value within its scale."
    )


def _normalize(value: Any, criterion: RubricCriterion) -> float:
    """Normalize a raw judge value into ``[0, 1]`` given a criterion's scale.

    Args:
        value: Raw value returned by the judge for this criterion, or
            ``None`` if the judge omitted it.
        criterion: The criterion's weight/scale configuration.

    Returns:
        The normalized value, clamped to ``[0, 1]``. Missing or non-numeric
        values normalize to ``0.0``.
    """
    if value is None:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    low, high = criterion.scale
    if high <= low:
        return 0.0
    normalized = (numeric - low) / (high - low)
    return max(0.0, min(1.0, normalized))


def default_evaluators() -> dict[str, Any]:
    """Return the built-in evaluator-kind dispatch table.

    Returns:
        A fresh ``{"deterministic": ..., "llm-as-judge": ...}`` mapping;
        callers may add entries for custom kinds without touching this module.
    """
    return {"deterministic": DeterministicEvaluator(), "llm-as-judge": LLMJudgeEvaluator()}


class EvalRunner:
    """Executes an :class:`EvalSpec`'s evaluators over a set of cases."""

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        evaluators: Mapping[str, Any] | None = None,
    ) -> None:
        """Initialize the runner with an LLM provider and evaluator dispatch table.

        Args:
            provider: LLM provider passed to ``llm-as-judge`` evaluators;
                defaults to the offline :class:`StubLLMProvider`.
            evaluators: Additional/overriding ``kind -> Evaluator`` entries,
                merged on top of :func:`default_evaluators`.
        """
        self._provider = provider or StubLLMProvider()
        self._evaluators: dict[str, Any] = default_evaluators()
        if evaluators:
            self._evaluators.update(evaluators)

    def register_evaluator(self, kind: str, evaluator: Any, *, replace: bool = False) -> None:
        """Register (or override) the evaluator used for a given kind.

        Args:
            kind: Evaluator kind string, e.g. ``"custom-metric"``.
            evaluator: An object implementing :class:`~backend.evals.contract.Evaluator`.
            replace: Whether to overwrite an already-registered kind.

        Raises:
            ValueError: If ``kind`` is already registered and ``replace`` is ``False``.
        """
        if kind in self._evaluators and not replace:
            raise ValueError(f"evaluator kind {kind!r} is already registered")
        self._evaluators[kind] = evaluator

    def run(self, spec: EvalSpec, cases: Sequence[EvalCase]) -> tuple[tuple[EvaluatorResult, ...], RunMetrics]:
        """Score every case with every evaluator and compute run metrics.

        Args:
            spec: The eval spec whose ``evaluators`` are executed.
            cases: Dataset cases to score, in order.

        Returns:
            A tuple of ``(evaluator_results, metrics)``.

        Raises:
            EvaluatorNotFoundError: If an evaluator's ``kind`` has no
                registered :class:`~backend.evals.contract.Evaluator`.
        """
        evaluator_results: list[EvaluatorResult] = []
        for evaluator_spec in spec.evaluators:
            evaluator = self._evaluators.get(evaluator_spec.kind)
            if evaluator is None:
                raise EvaluatorNotFoundError(f"no evaluator registered for kind {evaluator_spec.kind!r}")
            case_scores = tuple(
                evaluator.score(evaluator_spec, case, self._provider) for case in cases
            )
            mean_score = statistics.fmean(cs.score for cs in case_scores) if case_scores else 0.0
            evaluator_results.append(
                EvaluatorResult(evaluator_id=evaluator_spec.id, kind=evaluator_spec.kind, mean_score=mean_score, case_scores=case_scores)
            )
        metrics = _compute_metrics(evaluator_results, cases)
        return tuple(evaluator_results), metrics

    def evaluate_gate(self, gate: GateSpec | None, metrics: RunMetrics) -> tuple[bool, str]:
        """Evaluate the spec's quality gate against computed run metrics.

        Args:
            gate: The gate spec, or ``None`` if the spec declares no gate.
            metrics: The run's computed metrics.

        Returns:
            ``(passed, reason)`` — ``passed`` is ``True`` when no gate is
            declared, or when ``gate.fail_if`` evaluates to ``False``.

        Raises:
            EvalError: If ``gate.fail_if`` cannot be evaluated.
        """
        if gate is None:
            return True, "no gate configured"
        context = {
            "quality": {name: {"mean": value} for name, value in metrics.quality.items()},
            "cost": {"usd_mean": metrics.cost_usd_mean, "usd_p95": metrics.cost_usd_p95},
            "latency": {
                "p50_seconds": metrics.latency_p50_seconds,
                "p95_seconds": metrics.latency_p95_seconds,
            },
        }
        try:
            should_fail = evaluate_expression(gate.fail_if, context)
        except ExpressionError as exc:
            raise EvalError(f"invalid gate expression {gate.fail_if!r}: {exc}") from exc
        if should_fail:
            return False, f"fail_if matched: {gate.fail_if}"
        return True, f"fail_if did not match: {gate.fail_if}"


def _compute_metrics(evaluator_results: Sequence[EvaluatorResult], cases: Sequence[EvalCase]) -> RunMetrics:
    """Aggregate per-evaluator scores and per-case cost/latency into run metrics.

    Args:
        evaluator_results: Aggregated results from every evaluator in the run.
        cases: The dataset cases scored; ``cost_usd``/``latency_seconds`` in
            each case's payload feed the cost/latency metrics (defaulting to
            ``0.0`` when absent).

    Returns:
        The run's computed :class:`~backend.evals.results.RunMetrics`.
    """
    quality = {result.evaluator_id: result.mean_score for result in evaluator_results}
    costs = [float(case.payload.get("cost_usd", 0.0) or 0.0) for case in cases]
    latencies = [float(case.payload.get("latency_seconds", 0.0) or 0.0) for case in cases]
    return RunMetrics(
        quality=quality,
        cost_usd_mean=statistics.fmean(costs) if costs else 0.0,
        cost_usd_p95=_percentile(costs, 0.95),
        latency_p50_seconds=_percentile(latencies, 0.50),
        latency_p95_seconds=_percentile(latencies, 0.95),
    )


def _percentile(values: Sequence[float], fraction: float) -> float:
    """Compute a nearest-rank percentile of ``values``.

    Args:
        values: Sample values (need not be sorted).
        fraction: Desired percentile as a fraction in ``[0, 1]``, e.g. ``0.95``.

    Returns:
        The nearest-rank percentile value, or ``0.0`` for an empty sample.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


__all__ = [
    "DeterministicEvaluator",
    "EvalRunner",
    "LLMJudgeEvaluator",
    "default_evaluators",
]
