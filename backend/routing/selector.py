"""Selector pipeline executor (E5-S2, E5-S4).

Implements the ``selector:`` policy pipeline in full: ``capability-matching``
(client-side set intersection over
:meth:`backend.agents.registry_v2.AgentRegistry.find_by_capability`, per
ADR-008), ``cost-aware`` (objective-based ranking, filtered by the run's own
budget — tenant quotas are E11 and out of scope), and ``score-weighted``
(blends a published :class:`~backend.routing.contract.ScoreSnapshot` into the
ranking per the stage's configured ``weights``, E5-S4 — see
:mod:`backend.routing.feedback` for how a snapshot is published/promoted),
followed by the policy's ``tie_breaker`` for fully deterministic ordering.
The ``score-weighted`` stage's implementation itself lives in
:mod:`backend.routing.selector_scoring`, split out to keep both modules under
the repository's file-size guideline (mirrors the
:mod:`backend.routing.policy`/:mod:`backend.routing.selector_policy_parsing`
split).

Unlike the Router's ``rules`` pipeline (first-match-wins by confidence, see
:mod:`backend.routing.router`), the selector pipeline is a **sequential
transform**: each stage narrows or reorders the candidate list produced by the
previous stage, mirroring reference §9.3's ``selector.pipeline`` example
(capability-matching → cost-aware → score-weighted), not a cascade-on-failure.

Per-candidate ``model``/``reasoning_strategy`` are read from the candidate
:class:`~backend.agents.manifest.AgentManifest`'s free-form ``policy`` mapping
(no typed field exists on ``AgentManifest`` itself for either), falling back
to :data:`DEFAULT_MODEL`/:data:`DEFAULT_REASONING_STRATEGY` when absent — see
ADR-008's E5-S2 amendment for the rationale.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from packaging.version import Version

from backend.agents.manifest import AgentBudgets, AgentManifest
from backend.agents.registry_v2 import AgentRef, AgentRegistry
from backend.routing.contract import (
    ROUTING_CONTRACT_HOST_API,
    SELECT_SCHEMA_VERSION,
    ScoreSnapshot,
    SelectBudget,
    SelectDecision,
    SelectFallback,
    SelectRequest,
)
from backend.routing.policy import (
    RoutingPolicy,
    SelectorCapabilityMatchingStageSpec,
    SelectorCostAwareStageSpec,
    SelectorStageSpec,
)
from backend.routing.selector_scoring import SCORE_WEIGHTED_OBJECTIVE, apply_score_weighted

#: Model id used when a candidate agent's manifest declares no ``policy.model``.
DEFAULT_MODEL = "provider/default-model"

#: Reasoning Strategy (E4) id used when a candidate agent's manifest declares
#: no ``policy.reasoning_strategy``.
DEFAULT_REASONING_STRATEGY = "react"

#: Maximum number of cascade-fallback candidates carried on a SelectDecision.
MAX_FALLBACKS = 3


class NoEligibleAgentError(RuntimeError):
    """Raised when no registered agent survives the selector pipeline.

    Fail-closed per reference §9.6: rather than silently relaxing a filter
    (e.g. ignoring the run budget) to force a selection, the Selector raises
    so the caller can apply its own fallback/guardrail policy.
    """


class Selector:
    """Pluggable selector: executes a :class:`RoutingPolicy`'s ``selector`` pipeline.

    Structurally satisfies :class:`backend.routing.contract.SelectorPlugin`.
    Pure/stateless per call — ``select()`` never mutates instance state and
    never emits traces itself; :class:`backend.routing.service.RoutingService`
    is the layer responsible for tracing (mirrors :class:`backend.routing.router.Router`).
    """

    id = "autodev/selector-default"
    version = "1.0.0"
    host_api = ROUTING_CONTRACT_HOST_API

    def select(
        self,
        req: SelectRequest,
        policy: RoutingPolicy,
        registry: AgentRegistry,
        scores: ScoreSnapshot | None = None,
    ) -> SelectDecision:
        """Choose an agent/model/strategy by walking ``policy.selector``'s pipeline.

        Args:
            req: The request to resolve (route decision, required capabilities,
                run budget).
            policy: The routing policy in effect.
            registry: Agent Registry (E2) to match ``required_capabilities``
                against.
            scores: Optional Evaluation Service score snapshot (E5-S4);
                blended into ranking by a ``score-weighted`` pipeline stage,
                if the policy declares one (see
                :func:`backend.routing.selector_scoring.apply_score_weighted`).

        Returns:
            The resulting :class:`SelectDecision`, with up to
            :data:`MAX_FALLBACKS` cascade-fallback candidates.

        Raises:
            NoEligibleAgentError: If no registered agent survives the pipeline.
        """
        candidates = _run_pipeline(req, policy, registry, scores)
        if not candidates:
            raise NoEligibleAgentError(
                f"no registered agent satisfies required_capabilities={req.required_capabilities!r} "
                "under the active selector policy pipeline"
            )
        chosen, *rest = candidates
        return _to_decision(chosen, rest[:MAX_FALLBACKS], req.budget, scores)


def _run_pipeline(
    req: SelectRequest,
    policy: RoutingPolicy,
    registry: AgentRegistry,
    scores: ScoreSnapshot | None,
) -> list[AgentRef]:
    """Walk the selector pipeline's ordered stages, then apply the tie-breaker.

    Args:
        req: The select request being resolved.
        policy: The routing policy in effect.
        registry: Agent Registry to match against.
        scores: Optional Evaluation Service score snapshot.

    Returns:
        The final, deterministically ordered candidate list (most-preferred
        first); empty if no candidate survives.
    """
    candidates: list[AgentRef] | None = None
    objective = "minimize_cost"
    for stage in policy.selector.pipeline.stages:
        candidates, objective = _evaluate_stage(stage, req, registry, scores, candidates, objective)
    if candidates is None:
        # No capability-matching stage declared in the pipeline: fall back to
        # every registered agent (still subject to any cost-aware/score-weighted
        # stages that follow, and to the final deterministic ordering).
        candidates = registry.list_agents()
    return _deterministic_order(candidates, objective, policy.selector.pipeline.tie_breaker)


def _evaluate_stage(
    stage: SelectorStageSpec,
    req: SelectRequest,
    registry: AgentRegistry,
    scores: ScoreSnapshot | None,
    candidates: list[AgentRef] | None,
    objective: str,
) -> tuple[list[AgentRef], str]:
    """Dispatch and apply a single pipeline stage to the running candidate list.

    Args:
        stage: The stage spec to evaluate.
        req: The select request being resolved.
        registry: Agent Registry to match against.
        scores: Optional Evaluation Service score snapshot.
        candidates: The candidate list produced so far, or ``None`` if no
            stage has run yet.
        objective: The cost-aware objective selected so far (carried forward
            for the final deterministic ordering).

    Returns:
        The updated ``(candidates, objective)`` pair.
    """
    if isinstance(stage, SelectorCapabilityMatchingStageSpec):
        return _match_capabilities(registry, req.required_capabilities, stage.require_all, candidates), objective
    base = candidates if candidates is not None else registry.list_agents()
    if isinstance(stage, SelectorCostAwareStageSpec):
        return _apply_cost_aware(base, req.budget, stage), stage.objective
    weighted, applied = apply_score_weighted(base, stage, scores)
    return weighted, SCORE_WEIGHTED_OBJECTIVE if applied else objective


def _match_capabilities(
    registry: AgentRegistry,
    required_capabilities: Sequence[str],
    require_all: bool,
    candidates: list[AgentRef] | None = None,
) -> list[AgentRef]:
    """Match ``required_capabilities`` against the registry, client-side (ADR-008).

    Calls :meth:`AgentRegistry.find_by_capability` once per required
    capability (deduplicated, so a repeated entry in ``required_capabilities``
    cannot inflate a candidate's summed score) and intersects (``require_all``)
    or unions (not ``require_all``) the results by ``(agent_id, version)`` — a
    specific agent registration either declares a capability or it does not,
    so the same key appearing in every per-capability result set means that
    exact version supports all of them. A candidate's score across the
    matched capabilities is summed, so an agent covering more required
    capabilities ranks higher on ties.

    When ``candidates`` is given (i.e. an earlier pipeline stage already ran),
    results are additionally filtered down to that pool — this stage always
    *narrows* whatever the pipeline has produced so far, per the pipeline's
    sequential-transform contract (see the module docstring), regardless of
    where ``capability-matching`` is placed in the declared stage order.

    Args:
        registry: Agent Registry to search.
        required_capabilities: Capability ids the candidate must declare (all
            or any, per ``require_all``). An empty sequence matches every
            candidate already in ``candidates`` (or every registered agent,
            if this is the first stage).
        require_all: Whether a candidate must declare every capability
            (intersection) or just one (union).
        candidates: The candidate list produced by an earlier stage, or
            ``None`` if this is the first stage in the pipeline.

    Returns:
        Matching agent references, with capability-matching scores summed
        across every capability each one matched.
    """
    pool_keys: set[tuple[str, str]] | None = (
        {(candidate.agent_id, candidate.version) for candidate in candidates} if candidates is not None else None
    )
    if not required_capabilities:
        if candidates is not None:
            return list(candidates)
        return registry.list_agents()

    deduplicated_capabilities = list(dict.fromkeys(required_capabilities))
    per_capability: list[dict[tuple[str, str], AgentRef]] = [
        {
            (ref.agent_id, ref.version): ref
            for ref in registry.find_by_capability(capability)
            if pool_keys is None or (ref.agent_id, ref.version) in pool_keys
        }
        for capability in deduplicated_capabilities
    ]
    key_sets = [set(matches) for matches in per_capability]
    keys = set.intersection(*key_sets) if require_all else set.union(*key_sets)

    scores: dict[tuple[str, str], float] = {}
    references: dict[tuple[str, str], AgentRef] = {}
    for matches in per_capability:
        for key, ref in matches.items():
            if key not in keys:
                continue
            scores[key] = scores.get(key, 0.0) + ref.score
            references[key] = ref

    return [replace(references[key], score=scores[key]) for key in keys]


def _apply_cost_aware(
    candidates: list[AgentRef],
    budget: SelectBudget,
    spec: SelectorCostAwareStageSpec,
) -> list[AgentRef]:
    """Filter candidates that cannot fit the run's own budget.

    Tenant quotas (``spec.respect_tenant_quota``) are parsed but never
    enforced — E11 (multi-tenancy/quotas) is not built yet. This is a
    documented non-functional limitation for E5-S2 (reference §9.7 NF2).

    Args:
        candidates: The candidate list to filter.
        budget: The run's own requested budget.
        spec: The cost-aware stage configuration.

    Returns:
        Candidates whose own :class:`~backend.agents.manifest.AgentBudgets`
        fit inside ``budget``, if ``spec.respect_run_budget`` is set;
        otherwise ``candidates`` unchanged.
    """
    if not spec.respect_run_budget:
        return list(candidates)
    return [candidate for candidate in candidates if _fits_run_budget(candidate.manifest.budgets, budget)]


def _fits_run_budget(agent_budgets: AgentBudgets, run_budget: SelectBudget) -> bool:
    """Check whether an agent's own budget ceiling fits inside the run's budget.

    A ``run_budget`` component of ``0`` is treated as unconstrained for that
    dimension (``SelectBudget`` has no explicit "unset" sentinel).

    Args:
        agent_budgets: The candidate agent's own resource limits.
        run_budget: The run's requested budget ceiling.

    Returns:
        ``True`` if every constrained dimension of ``run_budget`` is met.
    """
    agent_tokens = agent_budgets.tokens_input + agent_budgets.tokens_output
    if run_budget.tokens > 0 and agent_tokens > run_budget.tokens:
        return False
    if run_budget.cost_usd > 0 and agent_budgets.cost_usd > run_budget.cost_usd:
        return False
    if run_budget.time_s > 0 and agent_budgets.wall_clock_seconds > run_budget.time_s:
        return False
    return True


def _deterministic_order(candidates: list[AgentRef], objective: str, tie_breaker: str) -> list[AgentRef]:
    """Sort candidates into a fully deterministic final order.

    Applies, from least to most significant (Python's sort is stable, so
    later passes take precedence): ``agent_id`` ascending, then registered
    ``version`` descending (prefer newer versions on a tie), then the policy's
    ``tie_breaker`` (only ``lowest_cost`` today), then the cost-aware
    ``objective``. Because the registry's primary key is ``(agent_id,
    version)``, no two candidates share both keys, so this ordering is total
    and independent of input order.

    Args:
        candidates: The candidate list to order.
        objective: One of ``minimize_cost``, ``minimize_latency``,
            ``maximize_quality`` (reference §9.3).
        tie_breaker: The policy's configured tie-breaker.

    Returns:
        A new list, ordered most-preferred first.
    """
    ordered = list(candidates)
    ordered.sort(key=lambda candidate: candidate.agent_id)
    ordered.sort(key=lambda candidate: Version(candidate.version), reverse=True)
    if tie_breaker == "lowest_cost":
        ordered.sort(key=lambda candidate: candidate.manifest.budgets.cost_usd)
    ordered.sort(key=lambda candidate: _objective_sort_key(candidate, objective))
    return ordered


def _objective_sort_key(candidate: AgentRef, objective: str) -> float:
    """Compute the ascending sort key for a candidate under a cost-aware objective.

    Args:
        candidate: The candidate agent reference.
        objective: One of ``minimize_cost``, ``minimize_latency``,
            ``maximize_quality``.

    Returns:
        A ``float`` such that ascending order matches the objective's
        preference (lower is always better for the returned key).
    """
    if objective == "minimize_latency":
        return float(candidate.manifest.budgets.wall_clock_seconds)
    if objective == "maximize_quality":
        return -candidate.score
    return candidate.manifest.budgets.cost_usd


def _resolve_model(manifest: AgentManifest) -> str:
    """Resolve the model id a candidate agent should run under.

    Reads an optional ``model`` key from the manifest's free-form ``policy``
    mapping (no typed field exists on :class:`AgentManifest` for this);
    falls back to :data:`DEFAULT_MODEL` when absent or not a string.

    Args:
        manifest: The candidate agent's manifest.

    Returns:
        The resolved model id.
    """
    value = manifest.policy.get("model")
    return value if isinstance(value, str) and value else DEFAULT_MODEL


def _resolve_reasoning_strategy(manifest: AgentManifest) -> str:
    """Resolve the Reasoning Strategy (E4) id a candidate agent should run under.

    Same convention as :func:`_resolve_model`, reading ``policy.reasoning_strategy``.

    Args:
        manifest: The candidate agent's manifest.

    Returns:
        The resolved reasoning strategy id.
    """
    value = manifest.policy.get("reasoning_strategy")
    return value if isinstance(value, str) and value else DEFAULT_REASONING_STRATEGY


def _select_budget_for_candidate(agent_budgets: AgentBudgets, run_budget: SelectBudget) -> SelectBudget:
    """Map a candidate's :class:`AgentBudgets` onto a :class:`SelectBudget`.

    Mirrors :func:`backend.reasoning.agent_binding.budget_from_agent_budgets`'s
    mapping shape (``tokens = tokens_input + tokens_output``, ``cost_usd``
    passthrough, ``time_s`` from ``wall_clock_seconds``) without importing
    that reasoning-specific module, then caps each dimension at the run's own
    requested budget (``0`` in ``run_budget`` means unconstrained). Tenant
    quotas (E11) are out of scope and not considered.

    Args:
        agent_budgets: The chosen candidate's own resource limits.
        run_budget: The run's requested budget ceiling.

    Returns:
        The resolved :class:`SelectBudget` for this run of the candidate.
    """
    agent_tokens = agent_budgets.tokens_input + agent_budgets.tokens_output
    tokens = min(agent_tokens, run_budget.tokens) if run_budget.tokens > 0 else agent_tokens
    cost_usd = min(agent_budgets.cost_usd, run_budget.cost_usd) if run_budget.cost_usd > 0 else agent_budgets.cost_usd
    time_s = (
        min(agent_budgets.wall_clock_seconds, run_budget.time_s)
        if run_budget.time_s > 0
        else agent_budgets.wall_clock_seconds
    )
    return SelectBudget(tokens=tokens, cost_usd=cost_usd, time_s=time_s)


def _to_decision(
    chosen: AgentRef,
    fallback_candidates: list[AgentRef],
    run_budget: SelectBudget,
    scores: ScoreSnapshot | None,
) -> SelectDecision:
    """Build the public :class:`SelectDecision` from the chosen candidate.

    Args:
        chosen: The winning candidate.
        fallback_candidates: Remaining candidates, most-preferred first.
        run_budget: The run's requested budget ceiling.
        scores: The score snapshot considered for this decision, if any.

    Returns:
        The resulting, publicly typed :class:`SelectDecision`.
    """
    return SelectDecision(
        schema_version=SELECT_SCHEMA_VERSION,
        agent_id=chosen.agent_id,
        agent_version=chosen.version,
        model=_resolve_model(chosen.manifest),
        reasoning_strategy=_resolve_reasoning_strategy(chosen.manifest),
        budget=_select_budget_for_candidate(chosen.manifest.budgets, run_budget),
        fallbacks=tuple(
            SelectFallback(
                agent_id=candidate.agent_id,
                model=_resolve_model(candidate.manifest),
                reasoning_strategy=_resolve_reasoning_strategy(candidate.manifest),
            )
            for candidate in fallback_candidates
        ),
        score_basis=scores.snapshot_id if scores is not None else "",
    )


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_REASONING_STRATEGY",
    "MAX_FALLBACKS",
    "NoEligibleAgentError",
    "Selector",
]
