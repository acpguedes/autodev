"""Typed Evaluation Service contract (E5-S3).

Defines the versioned surface an ``eval.yaml`` spec parses into and the
pluggable :class:`Evaluator` extension point (``deterministic`` /
``llm-as-judge`` / custom). Spec parsing/validation lives in
:mod:`backend.evals.spec`; the immutable, persisted run outcome lives in
:mod:`backend.evals.results`.

See ``docs/architecture/v2_platform_reference.md`` §9.4 for the canonical
(pt-BR) specification this module implements, and
``docs/v2_platform/decisions/RFC-005-evaluation-service-contract.md`` for the
contract rationale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from backend.agents.provider import LLMProvider

#: Compatibility range this contract module implements. Bump only on a
#: breaking (MAJOR) change to the dataclasses/Protocol below.
EVAL_CONTRACT_HOST_API = ">=2.0 <3.0"

EVAL_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

#: Valid values for :attr:`EvalSpec.mode`.
MODES = frozenset({"offline", "online"})


class EvalError(RuntimeError):
    """Base class for errors raised by the Evaluation Service."""


class EvaluatorNotFoundError(EvalError):
    """Raised when an eval spec references an unregistered evaluator kind."""


class EvalResultConflictError(EvalError):
    """Raised when a run/registration would collide with an already-stored,
    immutable ``(eval_id, eval_version, run_id)`` result (see ADR-009: results
    are never overwritten)."""


@dataclass(frozen=True)
class TraceEvent:
    """One ordered step in an eval run's trace.

    Mirrors the shape of :class:`backend.reasoning.contract.TraceEvent` (same
    ``on_event`` sink pattern) but is defined independently here so the
    Evaluation Service does not depend on the Reasoning Engine module for an
    unrelated cross-cutting concern (see ADR-009).

    Attributes:
        sequence: Monotonically increasing position of this event in the run.
        name: Dotted event name, e.g. ``"eval.run.completed"`` or
            ``"eval.run.failed"``.
        payload: Event-specific structured data.
        timestamp: Unix timestamp (seconds) the event was emitted at.
    """

    sequence: int
    name: str
    payload: dict[str, Any]
    timestamp: float


# ---------------------------------------------------------------------------
# Eval spec data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalTarget:
    """What an eval spec measures.

    Attributes:
        kind: Kind of target being evaluated, e.g. ``"agent"``.
        agent_id: Fully qualified Agent Registry (E2) id being evaluated.
        reasoning_strategy: Optional Reasoning Strategy (E4) id, when the eval
            measures a specific agent+strategy combination.
    """

    kind: str
    agent_id: str
    reasoning_strategy: str | None = None


@dataclass(frozen=True)
class EvalDataset:
    """Reference to the dataset an eval runs over.

    Attributes:
        ref: Dataset identifier, e.g. ``"autodev/bugfix-golden@2026-06"``.
        split: Dataset split evaluated, e.g. ``"test"``.
        size: Expected number of cases in the split (recorded for audit; the
            runner scores whatever cases it is actually given — see
            ``docs/evals/spec.md`` for the dataset-loading scope boundary).
    """

    ref: str
    split: str = "test"
    size: int = 0


@dataclass(frozen=True)
class RubricCriterion:
    """One weighted criterion of an ``llm-as-judge`` evaluator's rubric.

    Attributes:
        weight: Relative weight of this criterion in the evaluator's score.
        scale: Inclusive ``(min, max)`` range the judge scores this criterion on.
    """

    weight: float
    scale: tuple[float, float] = (0.0, 1.0)


@dataclass(frozen=True)
class EvaluatorSpec:
    """One entry of an eval spec's ``evaluators`` list.

    Attributes:
        kind: Evaluator kind dispatched to an :class:`Evaluator` implementation,
            e.g. ``"deterministic"`` or ``"llm-as-judge"``. Custom kinds are
            supported by registering an :class:`Evaluator` for them — the kind
            string itself is not restricted to a fixed enum.
        id: Identifier of this evaluator within the spec, used to key its
            score in the run's aggregated results and in gate expressions.
        check: Deterministic boolean expression evaluated against a case's
            payload, e.g. ``"patch.dry_run.ok == true"``. Required for kind
            ``"deterministic"``.
        model: Judge model identifier, recorded for audit/reproducibility.
            Required for kind ``"llm-as-judge"``.
        rubric: Named, weighted scoring criteria. Required (non-empty) for
            kind ``"llm-as-judge"``.
    """

    kind: str
    id: str
    check: str | None = None
    model: str | None = None
    rubric: dict[str, RubricCriterion] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityMetricSpec:
    """Quality metric configuration.

    Attributes:
        primary: Id of the evaluator whose mean score is the primary quality
            signal.
        aggregate: Aggregation function applied across cases, e.g. ``"mean"``.
        min_pass_rate: Minimum acceptable pass rate for ``primary``, recorded
            for audit; enforcement happens via ``gate.fail_if``.
    """

    primary: str
    aggregate: str = "mean"
    min_pass_rate: float | None = None


@dataclass(frozen=True)
class CostMetricSpec:
    """Cost metric configuration.

    Attributes:
        budget_usd_p95: Budget ceiling for the p95 cost in USD across cases,
            recorded for audit; enforcement happens via ``gate.fail_if``.
    """

    budget_usd_p95: float | None = None


@dataclass(frozen=True)
class LatencyMetricSpec:
    """Latency metric configuration.

    Attributes:
        p95_seconds: Budget ceiling for the p95 latency in seconds across
            cases, recorded for audit; enforcement happens via ``gate.fail_if``.
    """

    p95_seconds: float | None = None


@dataclass(frozen=True)
class MetricsSpec:
    """First-class metrics dimensions an eval spec declares.

    Attributes:
        quality: Quality metric configuration, if declared.
        cost: Cost metric configuration, if declared.
        latency: Latency metric configuration, if declared.
    """

    quality: QualityMetricSpec | None = None
    cost: CostMetricSpec | None = None
    latency: LatencyMetricSpec | None = None


@dataclass(frozen=True)
class GateSpec:
    """CI quality gate.

    Attributes:
        fail_if: Boolean expression over the run's metrics (see
            :mod:`backend.evals.expressions`); the gate fails when it is true.
    """

    fail_if: str


@dataclass(frozen=True)
class ABTestSpec:
    """Minimal, typed A/B test configuration for the ``online`` stub.

    No traffic-splitting/A-B infrastructure exists yet (E5-S4, future story);
    this dataclass only accepts and preserves the declared shape.

    Attributes:
        control: Control variant descriptor (e.g. ``{"policy": "..."}``).
        variant: Candidate variant descriptor.
        traffic: Traffic split configuration (e.g. ``{"variant_pct": 10}``).
        promote_if: Promotion criterion expression.
        min_samples: Minimum sample size before a promotion decision is made.
    """

    control: dict[str, Any] = field(default_factory=dict)
    variant: dict[str, Any] = field(default_factory=dict)
    traffic: dict[str, Any] = field(default_factory=dict)
    promote_if: str = ""
    min_samples: int = 0


@dataclass(frozen=True)
class OnlineConfig:
    """Typed-but-minimal ``online`` section of an eval spec.

    Attributes:
        publish_scores: Whether online scores should be published to the
            (not-yet-built) Selector score snapshot (E5-S4).
        ab_test: A/B test configuration, if declared.
    """

    publish_scores: bool = False
    ab_test: ABTestSpec | None = None


@dataclass(frozen=True)
class EvalSpec:
    """Fully parsed and validated ``eval.yaml`` document.

    Attributes:
        schema_version: Spec schema version.
        id: Fully qualified eval id in ``namespace/name`` format.
        version: SemVer version of the eval spec.
        target: What the eval measures.
        mode: ``"offline"`` or ``"online"``.
        dataset: Dataset reference the eval runs over.
        evaluators: Ordered evaluator entries.
        metrics: Declared quality/cost/latency metric configuration.
        gate: CI quality gate, if declared.
        online: Online publishing/A-B configuration, if declared.
        raw: Original parsed document.
    """

    schema_version: str
    id: str
    version: str
    target: EvalTarget
    mode: str
    dataset: EvalDataset
    evaluators: tuple[EvaluatorSpec, ...]
    metrics: MetricsSpec
    gate: GateSpec | None = None
    online: OnlineConfig | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalSpecValidationResult:
    """Outcome of validating a raw ``eval.yaml`` document.

    Attributes:
        valid: Whether the document passed validation.
        errors: Validation error messages, empty when ``valid`` is ``True``.
        spec: The parsed spec, present only when ``valid`` is ``True``.
    """

    valid: bool
    errors: list[str]
    spec: EvalSpec | None = None


# ---------------------------------------------------------------------------
# Evaluator extension point
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalCase:
    """A single dataset case scored by every evaluator in an eval run.

    Attributes:
        case_id: Identifier of this case within the dataset.
        payload: Structured data evaluators score against — e.g. a patch
            dry-run result, sandbox test outcome, candidate solution text, and
            optionally ``cost_usd``/``latency_seconds`` fields feeding the
            cost/latency metrics. Resolving ``dataset.ref`` into case payloads
            is out of scope for this story; callers supply cases directly
            (see ``docs/evals/spec.md``).
    """

    case_id: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalCaseScore:
    """Outcome of scoring one case with one evaluator.

    Attributes:
        case_id: Identifier of the scored case.
        evaluator_id: Identifier of the evaluator that produced this score.
        score: Normalized score in the closed interval ``[0, 1]``.
        details: Evaluator-specific explanation (e.g. rubric breakdown, or the
            checked expression and its boolean result).
    """

    case_id: str
    evaluator_id: str
    score: float
    details: dict[str, Any] = field(default_factory=dict)

    def to_document(self) -> dict[str, Any]:
        """Render this score as a JSON-serializable document."""
        return {
            "caseId": self.case_id,
            "evaluatorId": self.evaluator_id,
            "score": self.score,
            "details": self.details,
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "EvalCaseScore":
        """Parse a score back from its JSON document.

        Args:
            document: Document produced by :meth:`to_document`.

        Returns:
            The reconstructed :class:`EvalCaseScore`.
        """
        return cls(
            case_id=str(document["caseId"]),
            evaluator_id=str(document["evaluatorId"]),
            score=float(document["score"]),
            details=dict(document.get("details") or {}),
        )


class Evaluator(Protocol):
    """Pluggable scorer bound to one or more ``evaluators[]`` kinds.

    A single instance handles every :class:`EvaluatorSpec` of its kind within
    a run; per-evaluator configuration (``check``, ``model``, ``rubric``) is
    passed on every call so implementations may be stateless and shared.
    """

    def score(self, spec: EvaluatorSpec, case: EvalCase, provider: "LLMProvider") -> EvalCaseScore:
        """Score one dataset case against this evaluator's configuration.

        Args:
            spec: The evaluator's spec entry (kind/id/check/model/rubric).
            case: The dataset case to score.
            provider: LLM provider available to ``llm-as-judge`` evaluators;
                unused by deterministic ones.

        Returns:
            The case's score, normalized to ``[0, 1]``.
        """
        ...


__all__ = [
    "ABTestSpec",
    "CostMetricSpec",
    "EVAL_CONTRACT_HOST_API",
    "EVAL_ID_RE",
    "EvalCase",
    "EvalCaseScore",
    "EvalDataset",
    "EvalError",
    "EvalResultConflictError",
    "EvalSpec",
    "EvalSpecValidationResult",
    "EvalTarget",
    "Evaluator",
    "EvaluatorNotFoundError",
    "EvaluatorSpec",
    "GateSpec",
    "LatencyMetricSpec",
    "MODES",
    "MetricsSpec",
    "OnlineConfig",
    "QualityMetricSpec",
    "RubricCriterion",
    "SEMVER_RE",
    "TraceEvent",
]
