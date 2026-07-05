"""Rules-based Router pipeline executor (E5-S1).

Implements the ``rules`` pipeline stage in full: declarative ``when``/``set``
predicate matching, first-match-wins within a stage, and short-circuit by
confidence across stages (reference §9.3). The ``embeddings`` and
``llm-router`` stage kinds are typed extension-point stubs — present so a
:class:`~backend.routing.policy.RoutingPolicy` pipeline can declare them, but
they raise :class:`NotImplementedError` if the pipeline actually reaches one,
unless a caller injects a concrete implementation (see :class:`Router`'s
constructor).

Predicate matching reuses the operator-aware approach of
:mod:`backend.reasoning.selection` (``_match_value``/``_compare``/``_coerce``)
rather than importing it: the two matchers serve different domains (reasoning
selection signals vs. routing signals, the latter adding a ``~=`` regex
operator for free-text matching) and a small amount of duplication between two
small modules is preferable to a premature shared abstraction across epic
boundaries (repository working style).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from backend.routing.contract import (
    ROUTE_SCHEMA_VERSION,
    ROUTING_CONTRACT_HOST_API,
    ContextDigest,
    RouteConstraints,
    RouteDecision,
    RouteRequest,
)
from backend.routing.policy import (
    RouteConstraintsSpec,
    RouterDefaultSpec,
    RouterEmbeddingsStageSpec,
    RouterLLMStageSpec,
    RouterRuleSpec,
    RouterRulesStageSpec,
    RouterStageSpec,
    RoutingPolicy,
)

_OP_RE = re.compile(r"^(>=|<=|~=|==|>|<)\s*(.+)$")


@dataclass(frozen=True)
class _StageResult:
    """Internal outcome of evaluating a single pipeline stage.

    Attributes:
        task_type: Classified task type.
        intent: Classified intent.
        path: Suggested execution path.
        confidence: Confidence of this stage's classification, in ``[0, 1]``.
        constraints: Constraints to apply, or ``None`` to use the policy default.
        rationale: Human-readable justification for this result.
    """

    task_type: str
    intent: str
    path: tuple[str, ...]
    confidence: float
    constraints: RouteConstraintsSpec | None
    rationale: str


class EmbeddingsRouterStage(Protocol):
    """Pluggable ``embeddings`` router stage (pgvector/E7 extension point).

    Not implemented in E5-S1 (reference §9.3 describes similarity
    classification against labeled examples via pgvector, which depends on
    E7). Concrete implementations plug in by passing an instance to
    :class:`Router`'s ``embeddings_stage`` constructor argument.
    """

    def resolve(self, signals: Mapping[str, Any], spec: RouterEmbeddingsStageSpec) -> _StageResult | None:
        """Classify the signals against a labeled-examples dataset.

        Args:
            signals: Flattened request signals (see :func:`_build_signals`).
            spec: The ``embeddings`` stage configuration.

        Returns:
            A stage result if a classification above ``spec.threshold`` was
            found, else ``None`` to cascade to the next stage.
        """
        ...


class LLMRouterStage(Protocol):
    """Pluggable ``llm-router`` router stage (LLM-as-router extension point).

    Not implemented in E5-S1 (reference §9.3 describes an LLM classifying
    intent/task as a low-confidence desemper). Concrete implementations plug
    in by passing an instance to :class:`Router`'s ``llm_router_stage``
    constructor argument.
    """

    def resolve(self, signals: Mapping[str, Any], spec: RouterLLMStageSpec) -> _StageResult | None:
        """Classify the signals using an LLM-as-router call.

        Args:
            signals: Flattened request signals (see :func:`_build_signals`).
            spec: The ``llm-router`` stage configuration.

        Returns:
            A stage result, or ``None`` to cascade to the next stage.
        """
        ...


class _UnimplementedEmbeddingsStage:
    """Default ``embeddings`` stage handler: fails closed with a clear error."""

    def resolve(self, signals: Mapping[str, Any], spec: RouterEmbeddingsStageSpec) -> _StageResult | None:
        """Raise, since no embeddings backend is wired in E5-S1.

        Args:
            signals: Unused.
            spec: The ``embeddings`` stage configuration, echoed in the error.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            f"router pipeline stage 'embeddings' (dataset={spec.dataset!r}) has no backend in E5-S1; "
            "inject a concrete EmbeddingsRouterStage via Router(embeddings_stage=...) or remove the "
            "stage from the policy pipeline"
        )


class _UnimplementedLLMRouterStage:
    """Default ``llm-router`` stage handler: fails closed with a clear error."""

    def resolve(self, signals: Mapping[str, Any], spec: RouterLLMStageSpec) -> _StageResult | None:
        """Raise, since no LLM-as-router backend is wired in E5-S1.

        Args:
            signals: Unused.
            spec: The ``llm-router`` stage configuration, echoed in the error.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            f"router pipeline stage 'llm-router' (model={spec.model!r}) has no backend in E5-S1; "
            "inject a concrete LLMRouterStage via Router(llm_router_stage=...) or remove the stage "
            "from the policy pipeline"
        )


class Router:
    """Pluggable classifier: executes a :class:`RoutingPolicy`'s pipeline.

    Structurally satisfies :class:`backend.routing.contract.RouterPlugin`.
    Pure/stateless per call — ``route()`` never mutates instance state and
    never emits traces itself; :class:`backend.routing.service.RoutingService`
    is the layer responsible for tracing (mirrors the Reasoning Engine/Service
    split: the low-level executor stays a plain classifier, the service adds
    observability).
    """

    id = "autodev/router-rules"
    version = "1.0.0"
    host_api = ROUTING_CONTRACT_HOST_API

    def __init__(
        self,
        *,
        embeddings_stage: EmbeddingsRouterStage | None = None,
        llm_router_stage: LLMRouterStage | None = None,
    ) -> None:
        """Initialize the router, optionally with pluggable stage backends.

        Args:
            embeddings_stage: Backend for ``kind: embeddings`` stages; defaults
                to a stub that raises :class:`NotImplementedError` if reached.
            llm_router_stage: Backend for ``kind: llm-router`` stages; defaults
                to a stub that raises :class:`NotImplementedError` if reached.
        """
        self._embeddings_stage: EmbeddingsRouterStage = (
            embeddings_stage if embeddings_stage is not None else _UnimplementedEmbeddingsStage()
        )
        self._llm_router_stage: LLMRouterStage = (
            llm_router_stage if llm_router_stage is not None else _UnimplementedLLMRouterStage()
        )

    def route(
        self,
        req: RouteRequest,
        policy: RoutingPolicy,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> RouteDecision:
        """Classify ``req`` by walking ``policy.router``'s pipeline in order.

        Each stage is tried in turn; the first stage that produces a result
        with confidence at or above its ``confidence_floor`` short-circuits
        the pipeline. If no stage resolves a match, ``policy.router.default``
        is returned.

        Args:
            req: The request to classify.
            policy: The routing policy in effect.
            context: Additional signals layered on top of the ones derived
                from ``req`` (e.g. an ``intent`` hint from an upstream
                classifier); caller-supplied keys win on conflict.

        Returns:
            The resulting :class:`RouteDecision`.
        """
        signals = _build_signals(req, context)
        for stage in policy.router.stages:
            result = self._evaluate_stage(stage, signals)
            if result is not None and result.confidence >= _confidence_floor(stage):
                return _to_decision(result, policy.router.constraints)
        return _to_decision(_result_from_default(policy.router.default), policy.router.constraints)

    def _evaluate_stage(self, stage: RouterStageSpec, signals: Mapping[str, Any]) -> _StageResult | None:
        """Dispatch a single pipeline stage to its evaluator.

        Args:
            stage: The stage spec to evaluate.
            signals: Flattened request signals.

        Returns:
            A stage result if the stage resolved a match, else ``None``.
        """
        if isinstance(stage, RouterRulesStageSpec):
            return _evaluate_rules_stage(stage, signals)
        if isinstance(stage, RouterEmbeddingsStageSpec):
            return self._embeddings_stage.resolve(signals, stage)
        return self._llm_router_stage.resolve(signals, stage)


def _confidence_floor(stage: RouterStageSpec) -> float:
    """Return the confidence floor a stage's result must meet to short-circuit.

    Args:
        stage: The stage spec.

    Returns:
        The stage's configured confidence floor; ``0.0`` for stage kinds that
        do not declare one (embeddings/llm-router use their own thresholds
        internally, applied before returning a result at all).
    """
    if isinstance(stage, RouterRulesStageSpec):
        return stage.confidence_floor
    return 0.0


def _evaluate_rules_stage(stage: RouterRulesStageSpec, signals: Mapping[str, Any]) -> _StageResult | None:
    """Evaluate a ``rules`` stage: first-match-wins over its ordered rules.

    Args:
        stage: The rules stage spec.
        signals: Flattened request signals.

    Returns:
        A stage result for the first matching rule, else ``None``.
    """
    for index, rule in enumerate(stage.rules):
        if _matches(rule.when, signals):
            return _result_from_rule(rule, index)
    return None


def _result_from_rule(rule: RouterRuleSpec, index: int) -> _StageResult:
    """Build a :class:`_StageResult` from a matched declarative rule.

    Args:
        rule: The matched rule.
        index: The rule's position in its stage, used in the rationale.

    Returns:
        The stage result carrying the rule's ``set`` fields.
    """
    constraints_raw = rule.set.get("constraints")
    constraints = (
        RouteConstraintsSpec(
            max_cost_usd=float(constraints_raw.get("max_cost_usd", 0.05)),
            latency_class=str(constraints_raw.get("latency_class", "interactive")),
        )
        if isinstance(constraints_raw, dict)
        else None
    )
    return _StageResult(
        task_type=str(rule.set["task_type"]),
        intent=str(rule.set.get("intent", rule.set["task_type"])),
        path=tuple(str(node) for node in rule.set["path"]),
        confidence=rule.confidence,
        constraints=constraints,
        rationale=f"rules stage rule[{index}] matched: {rule.when!r}",
    )


def _result_from_default(default: RouterDefaultSpec) -> _StageResult:
    """Build a :class:`_StageResult` from the policy's fallback default.

    Args:
        default: The policy's default decision spec.

    Returns:
        The corresponding stage result.
    """
    return _StageResult(
        task_type=default.task_type,
        intent=default.intent,
        path=default.path,
        confidence=default.confidence,
        constraints=None,
        rationale=default.rationale,
    )


def _to_decision(result: _StageResult, default_constraints: RouteConstraintsSpec) -> RouteDecision:
    """Convert an internal stage result into a public :class:`RouteDecision`.

    Args:
        result: The stage result to convert.
        default_constraints: Constraints to apply when ``result.constraints``
            is ``None``.

    Returns:
        The resulting, publicly typed decision.
    """
    constraints = result.constraints or default_constraints
    return RouteDecision(
        schema_version=ROUTE_SCHEMA_VERSION,
        task_type=result.task_type,
        intent=result.intent,
        path=result.path,
        confidence=result.confidence,
        constraints=RouteConstraints(max_cost_usd=constraints.max_cost_usd, latency_class=constraints.latency_class),
        rationale=result.rationale,
    )


def _build_signals(req: RouteRequest, extra_context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Flatten a :class:`RouteRequest` into a dotted-path signal mapping.

    Args:
        req: The request to flatten.
        extra_context: Additional signals to layer on top (caller-supplied
            keys win over request-derived ones on conflict).

    Returns:
        A flat mapping suitable for rule predicate matching.
    """
    digest: ContextDigest = req.context_digest or ContextDigest()
    signals: dict[str, Any] = {
        "input.text": req.input.text,
        "input.attachments": list(req.input.attachments),
        "context.repo": digest.repo,
        "context.signals.has_tests": digest.signals.has_tests,
        "context.signals.languages": list(digest.signals.languages),
    }
    if extra_context:
        signals.update(extra_context)
    return signals


def _matches(when: Mapping[str, Any], signals: Mapping[str, Any]) -> bool:
    """Return whether every predicate in ``when`` holds for ``signals``.

    Args:
        when: Rule predicate mapping (dotted key to expected value/expression).
        signals: Flattened request signals to test.

    Returns:
        ``True`` if all predicates match (logical AND).
    """
    return all(_match_value(signals.get(key), expected) for key, expected in when.items())


def _match_value(actual: Any, expected: Any) -> bool:
    """Match a single actual value against an expected value or expression.

    Args:
        actual: The value from the flattened signals (``None`` if absent).
        expected: A literal, or an operator expression such as ``">=3"`` or
            ``"~=/pattern/"`` (a leading/trailing ``/`` around the pattern is
            optional and stripped before compiling).

    Returns:
        ``True`` if the actual value satisfies the expectation.
    """
    if actual is None:
        return False
    if isinstance(expected, bool):
        return bool(actual) == expected
    if isinstance(expected, str):
        match = _OP_RE.match(expected.strip())
        if match:
            return _compare(actual, match.group(1), match.group(2).strip())
        return _coerce(actual) == _coerce(expected)
    return bool(actual == expected)


def _compare(actual: Any, operator: str, value: str) -> bool:
    """Apply a comparison operator between an actual value and an expected one.

    Args:
        actual: The value from the flattened signals.
        operator: One of ``>=``, ``<=``, ``~=``, ``==``, ``>``, ``<``.
        value: The right-hand operand as a string.

    Returns:
        The boolean result; ``False`` when the operands are not comparable.
    """
    if operator == "~=":
        pattern = value[1:-1] if len(value) >= 2 and value.startswith("/") and value.endswith("/") else value
        try:
            return re.search(pattern, str(actual)) is not None
        except re.error:
            return False
    left: Any = _coerce(actual)
    right: Any = _coerce(value)
    if isinstance(left, float) != isinstance(right, float):
        return False
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    return left == right


def _coerce(value: Any) -> float | str:
    """Coerce a value to a float (if numeric) or a lowercase string.

    Args:
        value: The value to coerce.

    Returns:
        A ``float`` for numeric values, else a lowercase string.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value).strip().lower()


__all__ = [
    "EmbeddingsRouterStage",
    "LLMRouterStage",
    "Router",
]
