"""Evaluation Service and Evaluator extension point (epic E5, story E5-S3).

This package delivers the E5-S3 story: a typed, versioned ``eval.yaml``
contract (:mod:`backend.evals.contract`, :mod:`backend.evals.spec`), a
pluggable :class:`~backend.evals.contract.Evaluator` extension point with
``deterministic`` and ``llm-as-judge`` built-ins
(:mod:`backend.evals.runner`), the immutable/versioned run result
(:mod:`backend.evals.results`), and the service tying execution to durable
storage (:mod:`backend.evals.service`).

See ``docs/architecture/v2_platform_reference.md`` §9.4 for the full
specification and ``docs/evals/spec.md`` for the user-facing guide.
"""

from __future__ import annotations

from backend.evals.contract import (
    EVAL_CONTRACT_HOST_API,
    MODES,
    ABTestSpec,
    CostMetricSpec,
    EvalCase,
    EvalCaseScore,
    EvalDataset,
    EvalError,
    EvalResultConflictError,
    EvalSpec,
    EvalSpecValidationResult,
    EvalTarget,
    Evaluator,
    EvaluatorNotFoundError,
    EvaluatorSpec,
    GateSpec,
    LatencyMetricSpec,
    MetricsSpec,
    OnlineConfig,
    QualityMetricSpec,
    RubricCriterion,
    TraceEvent,
)
from backend.evals.expressions import ExpressionError, evaluate_expression
from backend.evals.results import EVAL_RESULT_SCHEMA_VERSION, EvalResult, EvaluatorResult, RunMetrics
from backend.evals.runner import DeterministicEvaluator, EvalRunner, LLMJudgeEvaluator, default_evaluators
from backend.evals.service import EvalResultStore, EvaluationService
from backend.evals.spec import load_eval_spec, validate_eval_spec

__all__ = [
    "ABTestSpec",
    "CostMetricSpec",
    "DeterministicEvaluator",
    "EVAL_CONTRACT_HOST_API",
    "EVAL_RESULT_SCHEMA_VERSION",
    "EvalCase",
    "EvalCaseScore",
    "EvalDataset",
    "EvalError",
    "EvalResult",
    "EvalResultConflictError",
    "EvalResultStore",
    "EvalRunner",
    "EvalSpec",
    "EvalSpecValidationResult",
    "EvalTarget",
    "Evaluator",
    "EvaluationService",
    "EvaluatorNotFoundError",
    "EvaluatorResult",
    "EvaluatorSpec",
    "ExpressionError",
    "GateSpec",
    "LLMJudgeEvaluator",
    "LatencyMetricSpec",
    "MODES",
    "MetricsSpec",
    "OnlineConfig",
    "QualityMetricSpec",
    "RubricCriterion",
    "RunMetrics",
    "TraceEvent",
    "default_evaluators",
    "evaluate_expression",
    "load_eval_spec",
    "validate_eval_spec",
]
