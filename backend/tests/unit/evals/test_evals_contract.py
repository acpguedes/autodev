"""Contract tests for the E5-S3 Evaluation Service ``eval.yaml`` spec.

Covers the story DoD: a well-formed ``eval.yaml`` document parses into a typed
:class:`EvalSpec` with all its nested sections (target, dataset, evaluators,
metrics, gate, online); malformed documents are rejected with actionable
errors; and the persisted result types (:class:`EvalResult`,
:class:`EvaluatorResult`, :class:`RunMetrics`, :class:`EvalCaseScore`)
round-trip through their ``to_document``/``from_document`` JSON boundary
unchanged — a precondition for durable storage.
"""

from __future__ import annotations

from typing import Any

from backend.evals.contract import (
    EVAL_CONTRACT_HOST_API,
    MODES,
    EvalCase,
    EvalCaseScore,
)
from backend.evals.results import EvalResult, EvaluatorResult, RunMetrics
from backend.evals.spec import validate_eval_spec


def _valid_raw_spec() -> dict[str, Any]:
    """Build a well-formed raw ``eval.yaml`` document for tests."""
    return {
        "schemaVersion": "1.0",
        "id": "autodev/eval-coder-bugfix",
        "version": "2.1.0",
        "target": {
            "kind": "agent",
            "agent_id": "autodev/agent-coder",
            "reasoning_strategy": "plan-and-execute",
        },
        "mode": "offline",
        "dataset": {"ref": "autodev/bugfix-golden@2026-06", "split": "test", "size": 240},
        "evaluators": [
            {"kind": "deterministic", "id": "patch_applies", "check": "patch.dry_run.ok == true"},
            {"kind": "deterministic", "id": "tests_pass", "check": "sandbox.tests.exit_code == 0"},
            {
                "kind": "llm-as-judge",
                "id": "solution_quality",
                "model": "provider/judge-large",
                "rubric": {
                    "correctness": {"weight": 0.5, "scale": [0, 1]},
                    "minimality": {"weight": 0.3, "scale": [0, 1]},
                    "style": {"weight": 0.2, "scale": [0, 1]},
                },
            },
        ],
        "metrics": {
            "quality": {"primary": "tests_pass", "aggregate": "mean", "min_pass_rate": 0.80},
            "cost": {"budget_usd_p95": 0.35},
            "latency": {"p95_seconds": 45},
        },
        "gate": {"fail_if": "quality.tests_pass.mean < 0.80 or cost.usd_p95 > 0.35"},
        "online": {
            "publish_scores": True,
            "ab_test": {
                "control": {"policy": "autodev/routing-default@1.4.0"},
                "variant": {"policy": "autodev/routing-default@1.5.0-rc"},
                "traffic": {"variant_pct": 10},
                "promote_if": "variant.quality >= control.quality and variant.cost <= control.cost",
                "min_samples": 500,
            },
        },
    }


# --------------------------------------------------------------------------
# Contract surface
# --------------------------------------------------------------------------


def test_contract_constants() -> None:
    """The contract exposes the expected host-API range and mode set."""
    assert EVAL_CONTRACT_HOST_API == ">=2.0 <3.0"
    assert MODES == {"offline", "online"}


# --------------------------------------------------------------------------
# Spec validation
# --------------------------------------------------------------------------


def test_valid_spec_parses_every_section() -> None:
    """A well-formed eval.yaml parses into a fully-populated EvalSpec."""
    result = validate_eval_spec(_valid_raw_spec())
    assert result.valid is True
    assert result.errors == []
    spec = result.spec
    assert spec is not None

    assert spec.id == "autodev/eval-coder-bugfix"
    assert spec.version == "2.1.0"
    assert spec.mode == "offline"
    assert spec.target.kind == "agent"
    assert spec.target.agent_id == "autodev/agent-coder"
    assert spec.target.reasoning_strategy == "plan-and-execute"
    assert spec.dataset.ref == "autodev/bugfix-golden@2026-06"
    assert spec.dataset.size == 240
    assert [evaluator.id for evaluator in spec.evaluators] == [
        "patch_applies",
        "tests_pass",
        "solution_quality",
    ]
    judge = spec.evaluators[2]
    assert judge.kind == "llm-as-judge"
    assert judge.model == "provider/judge-large"
    assert judge.rubric["correctness"].weight == 0.5
    assert judge.rubric["correctness"].scale == (0.0, 1.0)
    assert spec.metrics.quality is not None
    assert spec.metrics.quality.primary == "tests_pass"
    assert spec.metrics.quality.min_pass_rate == 0.80
    assert spec.metrics.cost is not None
    assert spec.metrics.cost.budget_usd_p95 == 0.35
    assert spec.metrics.latency is not None
    assert spec.metrics.latency.p95_seconds == 45
    assert spec.gate is not None
    assert "quality.tests_pass.mean" in spec.gate.fail_if
    assert spec.online is not None
    assert spec.online.publish_scores is True
    assert spec.online.ab_test is not None
    assert spec.online.ab_test.min_samples == 500
    assert spec.online.ab_test.promote_if.startswith("variant.quality")


def test_missing_top_level_keys_are_reported() -> None:
    """Every required top-level key is validated independently."""
    result = validate_eval_spec({})
    assert result.valid is False
    for key in ("schemaVersion", "id", "version", "target", "mode", "dataset", "evaluators", "metrics"):
        assert any(key in error for error in result.errors), f"missing error for {key!r}"


def test_bad_id_and_version_and_mode_are_rejected() -> None:
    """A malformed id, non-SemVer version, and unknown mode are each rejected."""
    raw = _valid_raw_spec()
    raw["id"] = "Not A Valid Id"
    raw["version"] = "not-semver"
    raw["mode"] = "sideways"
    result = validate_eval_spec(raw)
    assert result.valid is False
    assert any("id must use" in error for error in result.errors)
    assert any("version must be SemVer" in error for error in result.errors)
    assert any("mode must be one of" in error for error in result.errors)


def test_deterministic_evaluator_requires_check() -> None:
    """A deterministic evaluator without 'check' fails validation."""
    raw = _valid_raw_spec()
    raw["evaluators"] = [{"kind": "deterministic", "id": "no-check"}]
    result = validate_eval_spec(raw)
    assert result.valid is False
    assert any("requires 'check'" in error for error in result.errors)


def test_llm_as_judge_requires_nonempty_rubric() -> None:
    """An llm-as-judge evaluator without a rubric fails validation."""
    raw = _valid_raw_spec()
    raw["evaluators"] = [{"kind": "llm-as-judge", "id": "no-rubric", "model": "provider/x"}]
    result = validate_eval_spec(raw)
    assert result.valid is False
    assert any("requires a non-empty 'rubric'" in error for error in result.errors)


def test_duplicate_evaluator_ids_are_rejected() -> None:
    """Two evaluators sharing an id fail validation instead of silently colliding.

    Regression: metrics.quality is keyed by evaluator id, so a duplicate id
    would silently drop one evaluator's score when both means land under the
    same key.
    """
    raw = _valid_raw_spec()
    raw["evaluators"] = [
        {"kind": "deterministic", "id": "tests_pass", "check": "a == true"},
        {"kind": "deterministic", "id": "tests_pass", "check": "b == true"},
    ]
    result = validate_eval_spec(raw)
    assert result.valid is False
    assert any("duplicate id" in error for error in result.errors)


def test_gate_requires_fail_if_when_present() -> None:
    """A gate section without 'fail_if' fails validation."""
    raw = _valid_raw_spec()
    raw["gate"] = {}
    result = validate_eval_spec(raw)
    assert result.valid is False
    assert any("gate.fail_if is required" in error for error in result.errors)


def test_spec_without_gate_or_online_is_still_valid() -> None:
    """gate and online are optional sections."""
    raw = _valid_raw_spec()
    del raw["gate"]
    del raw["online"]
    result = validate_eval_spec(raw)
    assert result.valid is True
    assert result.spec is not None
    assert result.spec.gate is None
    assert result.spec.online is None


# --------------------------------------------------------------------------
# Persisted result round-trips (to_document / from_document)
# --------------------------------------------------------------------------


def test_eval_case_score_round_trips() -> None:
    """An EvalCaseScore survives a to_document/from_document round trip."""
    score = EvalCaseScore(case_id="c1", evaluator_id="tests_pass", score=1.0, details={"passed": True})
    restored = EvalCaseScore.from_document(score.to_document())
    assert restored == score


def test_evaluator_result_round_trips() -> None:
    """An EvaluatorResult (with nested case scores) round-trips unchanged."""
    result = EvaluatorResult(
        evaluator_id="tests_pass",
        kind="deterministic",
        mean_score=0.5,
        case_scores=(
            EvalCaseScore(case_id="c1", evaluator_id="tests_pass", score=1.0, details={}),
            EvalCaseScore(case_id="c2", evaluator_id="tests_pass", score=0.0, details={}),
        ),
    )
    restored = EvaluatorResult.from_document(result.to_document())
    assert restored == result


def test_eval_result_round_trips() -> None:
    """A full EvalResult document round-trips through JSON unchanged."""
    result = EvalResult(
        eval_id="autodev/eval-coder-bugfix",
        eval_version="2.1.0",
        run_id="run-1",
        mode="offline",
        dataset_ref="autodev/bugfix-golden@2026-06",
        dataset_split="test",
        dataset_size=2,
        evaluator_results=(
            EvaluatorResult(evaluator_id="tests_pass", kind="deterministic", mean_score=1.0, case_scores=()),
        ),
        metrics=RunMetrics(quality={"tests_pass": 1.0}, cost_usd_mean=0.1, cost_usd_p95=0.2),
        gate_passed=True,
        gate_reason="no gate configured",
        created_at="2026-07-05T00:00:00+00:00",
    )
    document = result.to_document()
    assert document["schemaVersion"] == "1"
    restored = EvalResult.from_document(document)
    assert restored == result


def test_eval_case_defaults_to_empty_payload() -> None:
    """EvalCase.payload defaults to an empty dict when omitted."""
    case = EvalCase(case_id="c1")
    assert case.payload == {}
