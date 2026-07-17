"""Runner/service tests for the E5-S3 Evaluation Service.

Covers the story DoD: a deterministic evaluator produces a score from a
boolean check against a case payload; an ``llm-as-judge`` evaluator produces a
rubric-weighted score via the offline stub :class:`LLMProvider`; the
``gate.fail_if`` quality gate blocks or passes a run; a custom
:class:`Evaluator` kind plugs in without touching :mod:`backend.evals.runner`;
and :class:`EvaluationService` persists an immutable, versioned
:class:`EvalResult` per run — re-running never overwrites a prior result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.agents.provider import StubLLMProvider
from backend.evals.contract import (
    EvalCase,
    EvalCaseScore,
    EvalError,
    EvalResultConflictError,
    EvaluatorNotFoundError,
    EvaluatorSpec,
)
from backend.evals.runner import DeterministicEvaluator, EvalRunner, LLMJudgeEvaluator
from backend.evals.service import EvaluationService
from backend.evals.spec import validate_eval_spec
from backend.persistence.sqlite_adapter import SQLiteStore


def _spec(raw_overrides: dict[str, Any] | None = None) -> Any:
    """Build a validated EvalSpec for tests, with optional field overrides."""
    raw: dict[str, Any] = {
        "schemaVersion": "1.0",
        "id": "autodev/eval-coder-bugfix",
        "version": "1.0.0",
        "target": {"kind": "agent", "agent_id": "autodev/agent-coder"},
        "mode": "offline",
        "dataset": {"ref": "autodev/bugfix-golden@2026-06", "split": "test", "size": 2},
        "evaluators": [
            {"kind": "deterministic", "id": "tests_pass", "check": "sandbox.tests.exit_code == 0"},
        ],
        "metrics": {"quality": {"primary": "tests_pass"}},
        **(raw_overrides or {}),
    }
    result = validate_eval_spec(raw)
    assert result.valid, result.errors
    assert result.spec is not None
    return result.spec


# --------------------------------------------------------------------------
# DeterministicEvaluator
# --------------------------------------------------------------------------


def test_deterministic_evaluator_scores_true_and_false() -> None:
    """A deterministic evaluator scores 1.0 for a true check and 0.0 for false."""
    evaluator = DeterministicEvaluator()
    spec = EvaluatorSpec(kind="deterministic", id="tests_pass", check="sandbox.tests.exit_code == 0")
    provider = StubLLMProvider()

    passing = evaluator.score(spec, EvalCase("c1", {"sandbox": {"tests": {"exit_code": 0}}}), provider)
    failing = evaluator.score(spec, EvalCase("c2", {"sandbox": {"tests": {"exit_code": 1}}}), provider)

    assert passing.score == 1.0
    assert passing.details["passed"] is True
    assert failing.score == 0.0
    assert failing.details["passed"] is False


def test_deterministic_evaluator_fails_soft_on_bad_expression() -> None:
    """An invalid or unresolvable check yields a 0.0 score with an error detail, not an exception."""
    evaluator = DeterministicEvaluator()
    spec = EvaluatorSpec(kind="deterministic", id="broken", check="sandbox.unknown_field == 1")
    score = evaluator.score(spec, EvalCase("c1", {"sandbox": {}}), StubLLMProvider())
    assert score.score == 0.0
    assert "error" in score.details


# --------------------------------------------------------------------------
# LLMJudgeEvaluator
# --------------------------------------------------------------------------


def test_llm_judge_evaluator_computes_weighted_score() -> None:
    """The judge evaluator normalizes and weights the judge's rubric response."""
    from backend.evals.contract import RubricCriterion

    spec = EvaluatorSpec(
        kind="llm-as-judge",
        id="solution_quality",
        model="provider/judge-large",
        rubric={
            "correctness": RubricCriterion(weight=0.5, scale=(0.0, 1.0)),
            "minimality": RubricCriterion(weight=0.3, scale=(0.0, 1.0)),
            "style": RubricCriterion(weight=0.2, scale=(0.0, 10.0)),
        },
    )
    provider = StubLLMProvider(text=json.dumps({"correctness": 1.0, "minimality": 0.5, "style": 5.0}))
    evaluator = LLMJudgeEvaluator()
    score = evaluator.score(spec, EvalCase("c1", {"candidate": "def fix(): ..."}), provider)

    # correctness: 1.0 * 0.5 = 0.5; minimality: 0.5 * 0.3 = 0.15; style: (5/10)=0.5 * 0.2 = 0.1
    assert score.score == pytest.approx(0.75)
    assert score.details["breakdown"]["style"] == pytest.approx(0.5)


def test_llm_judge_evaluator_fails_soft_on_invalid_json() -> None:
    """A non-JSON judge response yields a 0.0 score with an error detail, not an exception."""
    from backend.evals.contract import RubricCriterion

    spec = EvaluatorSpec(
        kind="llm-as-judge",
        id="solution_quality",
        model="provider/judge-large",
        rubric={"correctness": RubricCriterion(weight=1.0)},
    )
    provider = StubLLMProvider(text="not json at all")
    evaluator = LLMJudgeEvaluator()
    score = evaluator.score(spec, EvalCase("c1", {"candidate": "x"}), provider)
    assert score.score == 0.0
    assert "error" in score.details


def test_llm_judge_evaluator_missing_criterion_scores_zero_for_it() -> None:
    """A criterion omitted from the judge's response normalizes to 0.0, not an exception."""
    from backend.evals.contract import RubricCriterion

    spec = EvaluatorSpec(
        kind="llm-as-judge",
        id="solution_quality",
        rubric={
            "correctness": RubricCriterion(weight=0.5),
            "style": RubricCriterion(weight=0.5),
        },
    )
    provider = StubLLMProvider(text=json.dumps({"correctness": 1.0}))
    score = LLMJudgeEvaluator().score(spec, EvalCase("c1", {}), provider)
    assert score.details["breakdown"]["style"] == 0.0
    assert score.score == pytest.approx(0.5)


# --------------------------------------------------------------------------
# EvalRunner: aggregation, metrics, gate
# --------------------------------------------------------------------------


def test_runner_aggregates_scores_and_computes_metrics() -> None:
    """The runner means per-evaluator scores and computes cost/latency percentiles."""
    spec = _spec()
    cases = [
        EvalCase("c1", {"sandbox": {"tests": {"exit_code": 0}}, "cost_usd": 0.1, "latency_seconds": 5}),
        EvalCase("c2", {"sandbox": {"tests": {"exit_code": 1}}, "cost_usd": 0.3, "latency_seconds": 15}),
    ]
    runner = EvalRunner()
    evaluator_results, metrics = runner.run(spec, cases)

    assert len(evaluator_results) == 1
    assert evaluator_results[0].mean_score == pytest.approx(0.5)
    assert metrics.quality["tests_pass"] == pytest.approx(0.5)
    assert metrics.cost_usd_mean == pytest.approx(0.2)
    assert metrics.latency_p50_seconds in (5.0, 15.0)  # nearest-rank percentile of a 2-item sample


def test_runner_raises_for_unregistered_evaluator_kind() -> None:
    """An evaluator kind with no registered Evaluator raises EvaluatorNotFoundError."""
    spec = _spec({"evaluators": [{"kind": "does-not-exist", "id": "x", "check": "a == true"}]})
    runner = EvalRunner()
    with pytest.raises(EvaluatorNotFoundError):
        runner.run(spec, [EvalCase("c1", {"a": True})])


def test_gate_blocks_when_fail_if_matches() -> None:
    """A gate whose fail_if expression matches the metrics reports a failing gate."""
    spec = _spec({"gate": {"fail_if": "quality.tests_pass.mean < 0.80"}})
    runner = EvalRunner()
    cases = [EvalCase("c1", {"sandbox": {"tests": {"exit_code": 1}}})]  # scores 0.0 -> mean 0.0 < 0.80
    _, metrics = runner.run(spec, cases)
    passed, reason = runner.evaluate_gate(spec.gate, metrics)
    assert passed is False
    assert "fail_if matched" in reason


def test_gate_passes_when_fail_if_does_not_match() -> None:
    """A gate whose fail_if expression does not match reports a passing gate."""
    spec = _spec({"gate": {"fail_if": "quality.tests_pass.mean < 0.80"}})
    runner = EvalRunner()
    cases = [EvalCase("c1", {"sandbox": {"tests": {"exit_code": 0}}})]  # scores 1.0 -> mean 1.0, not < 0.80
    _, metrics = runner.run(spec, cases)
    passed, reason = runner.evaluate_gate(spec.gate, metrics)
    assert passed is True
    assert "did not match" in reason


def test_gate_passes_by_default_when_no_gate_declared() -> None:
    """No gate declared means the run always passes the (absent) gate."""
    runner = EvalRunner()
    passed, reason = runner.evaluate_gate(None, runner.run(_spec(), [EvalCase("c1", {})])[1])
    assert passed is True
    assert reason == "no gate configured"


def test_gate_raises_eval_error_on_invalid_expression() -> None:
    """A syntactically invalid fail_if expression raises EvalError, not a bare exception."""
    from backend.evals.contract import GateSpec

    runner = EvalRunner()
    _, metrics = runner.run(_spec(), [EvalCase("c1", {"sandbox": {"tests": {"exit_code": 0}}})])
    with pytest.raises(EvalError):
        runner.evaluate_gate(GateSpec(fail_if="quality.tests-pass.mean < 0.5"), metrics)  # hyphen: unsupported


# --------------------------------------------------------------------------
# Pluggability: a custom Evaluator kind, no core changes
# --------------------------------------------------------------------------


class _AlwaysHalfEvaluator:
    """A trivial custom Evaluator that always scores 0.5, for pluggability tests."""

    def score(self, spec: EvaluatorSpec, case: EvalCase, provider: Any) -> EvalCaseScore:
        """Return a fixed 0.5 score regardless of input."""
        del provider
        return EvalCaseScore(case_id=case.case_id, evaluator_id=spec.id, score=0.5, details={})


def test_custom_evaluator_kind_is_pluggable() -> None:
    """A brand-new evaluator kind can be registered and dispatched without touching the runner module."""
    spec = _spec({"evaluators": [{"kind": "always-half", "id": "custom", "check": None}]})
    runner = EvalRunner()
    runner.register_evaluator("always-half", _AlwaysHalfEvaluator())

    evaluator_results, _ = runner.run(spec, [EvalCase("c1", {}), EvalCase("c2", {})])
    assert evaluator_results[0].mean_score == pytest.approx(0.5)


def test_register_evaluator_rejects_duplicate_kind_unless_replace() -> None:
    """Re-registering a kind without replace=True raises; replace=True allows it."""
    runner = EvalRunner()
    with pytest.raises(ValueError):
        runner.register_evaluator("deterministic", _AlwaysHalfEvaluator())
    runner.register_evaluator("deterministic", _AlwaysHalfEvaluator(), replace=True)  # does not raise


# --------------------------------------------------------------------------
# EvaluationService: persistence, trace events, immutability
# --------------------------------------------------------------------------


@pytest.fixture()
def sqlite_store(tmp_path: Path) -> SQLiteStore:
    """A SQLiteStore backed by a throwaway database file, exercising the real eval_results table."""
    return SQLiteStore(f"sqlite:///{tmp_path / 'evals_test.db'}")


def test_service_run_offline_persists_result_and_emits_trace_events(sqlite_store: SQLiteStore) -> None:
    """run_offline persists the result and emits started/completed trace events."""
    events: list[str] = []
    service = EvaluationService(sqlite_store, on_event=lambda event: events.append(event.name))
    spec = _spec()
    cases = [EvalCase("c1", {"sandbox": {"tests": {"exit_code": 0}}})]

    result = service.run_offline(spec, cases)

    assert result.gate_passed is True
    assert events == ["eval.run.started", "eval.run.completed"]
    fetched = service.get_result(spec.id, spec.version, result.run_id)
    assert fetched == result


def test_service_rerun_produces_new_versioned_result_not_overwrite(sqlite_store: SQLiteStore) -> None:
    """Running the same spec twice stores two distinct, immutable results."""
    service = EvaluationService(sqlite_store)
    spec = _spec()
    cases = [EvalCase("c1", {"sandbox": {"tests": {"exit_code": 0}}})]

    first = service.run_offline(spec, cases)
    second = service.run_offline(spec, cases)

    assert first.run_id != second.run_id
    results = service.list_results(spec.id, spec.version)
    assert {r.run_id for r in results} == {first.run_id, second.run_id}
    # The first result is untouched by the second run.
    assert service.get_result(spec.id, spec.version, first.run_id) == first


def test_service_reusing_a_run_id_is_rejected_by_the_store(sqlite_store: SQLiteStore) -> None:
    """The store's UNIQUE(eval_id, eval_version, run_id) constraint enforces immutability.

    The service normalizes the backend's raw sqlite3.IntegrityError into a
    typed EvalResultConflictError (regression: this used to escape as a bare,
    backend-specific exception the API layer had no way to map to a clean
    4xx response).
    """
    events: list[str] = []
    service = EvaluationService(sqlite_store, on_event=lambda event: events.append(event.name))
    spec = _spec()
    cases = [EvalCase("c1", {"sandbox": {"tests": {"exit_code": 0}}})]

    service.run_offline(spec, cases, run_id="fixed-run-id")
    events.clear()
    with pytest.raises(EvalResultConflictError):
        service.run_offline(spec, cases, run_id="fixed-run-id")
    assert events == ["eval.run.started", "eval.run.failed"]


def test_service_register_online_reusing_a_run_id_is_rejected(sqlite_store: SQLiteStore) -> None:
    """register_online also raises EvalResultConflictError on a run_id collision."""
    service = EvaluationService(sqlite_store)
    spec = _spec({"mode": "online"})

    service.register_online(spec, run_id="fixed-online-run")
    with pytest.raises(EvalResultConflictError):
        service.register_online(spec, run_id="fixed-online-run")


def test_service_run_offline_rejects_online_spec(sqlite_store: SQLiteStore) -> None:
    """run_offline refuses a spec declaring mode='online'."""
    service = EvaluationService(sqlite_store)
    spec = _spec({"mode": "online"})
    with pytest.raises(EvalError):
        service.run_offline(spec, [EvalCase("c1", {})])


def test_service_register_online_persists_stub_without_running_anything(sqlite_store: SQLiteStore) -> None:
    """register_online persists the declared online config without executing evaluators."""
    events: list[str] = []
    service = EvaluationService(sqlite_store, on_event=lambda event: events.append(event.name))
    spec = _spec(
        {
            "mode": "online",
            "online": {
                "publish_scores": True,
                "ab_test": {
                    "control": {"policy": "autodev/routing-default@1.4.0"},
                    "variant": {"policy": "autodev/routing-default@1.5.0-rc"},
                    "traffic": {"variant_pct": 10},
                    "promote_if": "variant.quality >= control.quality",
                    "min_samples": 500,
                },
            },
        }
    )

    document = service.register_online(spec)

    assert document["mode"] == "online"
    assert document["online"]["publishScores"] is True
    assert document["online"]["abTest"]["minSamples"] == 500
    assert document["evaluators"] == []
    assert events == ["eval.run.registered_online"]
    stored = sqlite_store.get_eval_result(spec.id, spec.version, document["runId"])
    assert stored == document


def test_service_register_online_rejects_offline_spec(sqlite_store: SQLiteStore) -> None:
    """register_online refuses a spec declaring mode='offline'."""
    service = EvaluationService(sqlite_store)
    with pytest.raises(EvalError):
        service.register_online(_spec())


def test_service_list_results_empty_for_unknown_eval(sqlite_store: SQLiteStore) -> None:
    """Listing results for an eval id with no runs yet returns an empty list."""
    service = EvaluationService(sqlite_store)
    assert service.list_results("autodev/does-not-exist") == []
    assert service.get_result("autodev/does-not-exist", "1.0.0", "run-x") is None
