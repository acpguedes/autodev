# ADR-008 — Router & Selector Boundary and Enforcement Model

- **Status:** Accepted
- **Epic:** E5-S1
- **Date:** 2026-07-05
- **Related:** RFC-004 (contract surface), ADR-007 (reasoning engine boundary,
  for contrast), reference §9

## Context

E5 introduces the **Router** (this story) and, in a follow-up story, the
**Selector**, at the `router`/`selector` extension points (reference §9).
Four boundary questions had to be settled before implementation: (1) whether
the `RouterPlugin` contract is synchronous or asynchronous; (2) how a routing
decision is traced; (3) where capability-matching for the Selector will live;
and (4) whether to reuse `backend.reasoning.contract.TraceEvent` or define a
local equivalent.

## Decision

1. **Synchronous contract.** Unlike `ReasoningStrategy.run` (ADR-007),
   `RouterPlugin.route(req, policy) -> RouteDecision` is a plain synchronous
   call. Rationale: the `rules` pipeline stage — the only stage fully
   implemented in E5-S1 — is pure in-process predicate matching with no I/O,
   and the NF target is p95 < 150 ms (reference §9.7); an `async` contract
   would add no capability here and would force every caller (including the
   `POST /v2/route` handler, itself synchronous per the `agents_v2.py`
   pattern) to bridge with `asyncio.run` for no benefit. The `llm-router`
   stage stub, if implemented later with a real LLM call, stays internal to
   its own stage handler (`LLMRouterStage.resolve`) and can bridge to async
   there without touching the public contract.

2. **Trace ownership at the Service layer.** `Router.route()` is a pure
   classifier: no `on_event`, no side effects. `RoutingService.route()` is the
   sole place a decision is traced, emitting exactly one
   `router.decision.recorded` event per call (mirroring
   `ReasoningService`'s `reasoning.selection.decided` pattern, ADR-007 point
   2). This keeps the pluggable classifier trivial to test and reuse (e.g. a
   future Selector-side dry-run) independent of tracing concerns, while still
   satisfying the "every RouteDecision is traceable" DoD at the one place a
   decision is actually consumed.

3. **Selector capability matching (forward decision, informs E5-S2 design,
   not implemented this story).** The Selector's `required_capabilities`
   matching against the Agent Registry (E2) will be a client-side set
   intersection over `AgentRegistry.find_by_capability`
   (`backend/agents/registry_v2.py`), not a new registry method. The registry
   already exposes capability-scoped lookup for the `/v2/agents/catalog`
   endpoint (`backend/api/routers/agents_v2.py`); reusing it keeps the
   Registry's public surface unchanged across E5-S2 and avoids duplicating
   capability-indexing logic in two places.

4. **Local `TraceEvent`, not imported from Reasoning.** `backend.routing.contract.TraceEvent`
   is defined locally with a shape identical to
   `backend.reasoning.contract.TraceEvent` (`sequence`, `name`, `payload`,
   `timestamp`) rather than imported. The pipeline's actual data flow is
   Router → Selector → Agent Runtime (E2) + Reasoning Engine (E4) (reference
   §9.1 diagram) — Router is upstream of Reasoning, so a Router→Reasoning
   import would be a backwards dependency purely for type reuse. Both modules
   independently versioning their own trace-event shape also avoids one
   epic's contract churn forcing a lockstep change in the other, at the cost
   of the small, explicitly-documented duplication.

## Consequences

- (+) `RouterPlugin` is trivial to implement and test — no event loop, no
  mediator, just a function of `(req, policy)`.
- (+) `RoutingService` isolates tracing from classification, so a custom
  `RouterPlugin` (the pluggability DoD) never needs to know about `on_event`.
- (+) The Selector's capability matching (E5-S2) has a settled home
  (`AgentRegistry.find_by_capability`, client-side intersection) before that
  story starts, avoiding a mid-story registry API design detour.
- (−) `backend.routing.contract.TraceEvent` and
  `backend.reasoning.contract.TraceEvent` are two independent types with the
  same shape; a consumer that wants to treat both uniformly must convert
  between them (in practice, both flow into the same `on_event` sink type
  signature, so this is a non-issue for the common case of forwarding both to
  one Event Bus handler that only reads `.name`/`.payload`).
- Contract tests (`backend/tests/test_routing_contract.py`,
  `backend/tests/test_routing_router.py`) gate the Router implementation
  against this boundary; E5-S2 will add the analogous Selector contract tests
  when it implements `SelectorPlugin` against RFC-004's fixed shape.

## Amendment (E5-S2)

E5-S2 implements `SelectorPlugin` (`backend/routing/selector.py`) against
RFC-004's fixed `SelectRequest`/`SelectDecision` shape without changing it.
A few implementation details RFC-004 left open needed settling:

1. **Selector pipeline is a sequential transform, not a cascade.** Unlike the
   Router's `rules` stage (first-match-wins by confidence), each selector
   stage (`capability-matching`, `cost-aware`, `score-weighted`) narrows or
   reorders the candidate list the previous stage produced — matching
   reference §9.3's pipeline example. `capability-matching` in particular
   filters whatever pool it is handed (falling back to the full registry only
   when it is the first stage to run), so it behaves correctly regardless of
   where a policy places it in the declared stage order.
2. **`model`/`reasoning_strategy` resolution.** Neither field exists as a
   typed slot on `AgentManifest` (E2). The Selector reads optional
   `policy.model`/`policy.reasoning_strategy` keys from the candidate's
   free-form `AgentManifest.policy` mapping, falling back to module-level
   defaults (`DEFAULT_MODEL`, `DEFAULT_REASONING_STRATEGY = "react"`) when
   absent. A future story may promote these to typed manifest fields; this
   convention is a documented placeholder, not a manifest schema change.
3. **Fail-closed on no eligible candidate.** If the pipeline (including a
   `cost-aware` stage's run-budget filter) leaves zero candidates, `select()`
   raises `NoEligibleAgentError` rather than silently relaxing a filter —
   consistent with reference §9.6's fail-closed default. `POST /v2/select`
   maps this to HTTP 422.
4. **Fallback list is capped** at `MAX_FALLBACKS = 3` remaining candidates,
   most-preferred first; RFC-004 does not specify a cap.
5. **Tenant quotas (`respect.tenant_quota`) are parsed but not enforced** — E11
   (multi-tenancy/quotas) is not built yet. Only the run's own budget
   (`SelectRequest.budget`) is respected. Same deferred-NFR pattern as E4.
6. **SDK contract surface** (`backend/sdk/contracts.py`) re-exports
   `SelectRequest`/`SelectDecision`/`SelectorPlugin`/`ScoreSnapshot`;
   `SDK_CONTRACT_VERSION` bumped 1.3.0 → 1.4.0 (additive/MINOR).

None of the above change the `SelectRequest`/`SelectDecision`/`SelectorPlugin`
shape RFC-004 fixed; they are implementation conventions the RFC did not
specify.

## Amendment (E5-S4)

E5-S4 closes the loop reference §9.5 describes: it wires the `score-weighted`
selector stage to a real `ScoreSnapshot` (E5-S3's Evaluation Service data) and
adds the regression-guarded promotion mechanism deciding *whether* a
published snapshot becomes a policy's active one. This is a MINOR, additive
change to `ScoreSnapshot` (new fields, all defaulted) and a behavioral wiring
of an already-declared stage kind — not a new public contract — so an ADR
amendment, not a new RFC, is the right instrument (per `agent_guide.md` §5).

1. **`ScoreSnapshot`'s final shape.** Additive to the E5-S2 placeholder: the
   existing `scores: dict[str, float]` (bare quality scalar per agent) is kept
   for backward compatibility; a new `agent_scores: dict[str,
   AgentScoreAggregate]` carries the full per-agent quality/cost/latency/
   sample-count breakdown the `score-weighted` stage and the promotion guard
   actually compute against. `sample_count` (total contributing
   `EvalResult` runs), `created_at`, and `source_run_ids` support the
   `min_samples` hysteresis guard and audit trail. `AgentScoreAggregate` and
   `ScoreSnapshot` both gained `to_document`/`from_document` for the same
   plain-JSON persistence/API convention `EvalResult` already uses.
2. **`score-weighted` stage: real ranking, not a new sort key.** Rather than
   add a fourth ranking dimension to `_deterministic_order`, the stage
   overwrites each candidate's existing `AgentRef.score` field (already
   documented as a general-purpose "ranking score used when searching by
   capability", and already consumed by the `maximize_quality` objective) with
   a blended value, then forces the final sort's objective to
   `maximize_quality`. This reuses 100% of the existing deterministic
   tie-break machinery — no new stage-specific sort path was introduced —
   at the cost of the stage's effect only being observable through an
   objective override rather than its own independent ranking key. Cost and
   latency are min-max normalized across the *current candidate pool* before
   being inverted (`1 - normalized`) so all three weighted terms share the
   `[0, 1]` scale despite quality being pre-normalized and cost/latency being
   raw USD/seconds; a candidate absent from the snapshot gets a neutral `0.0`.
   This is a no-op passthrough (unchanged E5-S2 behavior) whenever no snapshot
   is supplied, or the stage declares no `weights` — both remain valid,
   intentional configurations.
3. **Promotion/regression guard lives in a new module,
   `backend/routing/feedback.py`, not `selector.py`.** `RoutingFeedbackService`
   is a separate concern from the Selector itself: it decides *whether* a
   published `ScoreSnapshot` becomes a policy's active one (durable,
   cross-request state keyed by `policy_id`), while `Selector`/`selector.py`
   only *consumes* whatever active snapshot a caller passes in. Splitting them
   keeps the Selector pure/stateless per call (ADR-008 point 2's tracing
   split, mirrored here for promotion decisions).
4. **The regression criterion reuses `backend.evals.expressions.evaluate_expression`,
   not `backend.reasoning.selection`'s or `backend.routing.router`'s
   `key -> literal` predicate matchers.** Those two match one flattened signal
   against a literal/operator-expression string; `ABTestSpec.promote_if`
   (`"variant.quality >= control.quality and variant.cost <= control.cost"`)
   compares two *paths* joined by `and`/`or` — a shape neither matcher
   natively supports without building new top-level clause-splitting/path-
   resolution logic on top of them. `backend.evals.expressions` already
   implements exactly this dotted-identifier boolean-expression grammar for
   `gate.fail_if` (same package as `ABTestSpec`, same grammar), so it is
   reused as-is: zero new parsing logic, not a fourth predicate parser.
5. **Hysteresis guard is a simple sample-count floor, not a statistical
   test.** `ab_test.min_samples` (`0` = no minimum, mirroring
   `SelectBudget`'s "0 = unconstrained" convention) must be met by
   `candidate.sample_count` before `promote_if` is even evaluated. This is
   deliberately simple (no significance testing, no confidence intervals) —
   sufficient to satisfy the story's "no unstable loop" NFR without building
   an A/B statistics engine, which is out of scope.
6. **Every decision — promoted or blocked — is persisted and traced,
   never silently dropped.** `RoutingFeedbackService` records every call to
   `decide_promotion` via `record_snapshot_promotion` (a new, append-only
   `score_snapshot_promotions` table) and emits `selector.policy.adjusted` or
   `selector.policy.regression_blocked`, so a regression is auditable rather
   than an invisible no-op.
7. **`default_routing_policy()` gains a `score-weighted` stage** (`weights:
   {quality: 0.6, cost: 0.25, latency: 0.15}`, reference §9.3's example
   ratios) so the platform default policy's selector pipeline actually
   exercises the closed loop; before E5-S4 it only had `capability-matching`
   and `cost-aware`. This is additive to the pipeline's stage list, not a
   change to any existing stage's behavior when no snapshot is promoted yet.
8. **`POST /v2/select` looks up the active snapshot itself**, via a new
   `RoutingFeedbackService` dependency in `backend/api/routers/routing.py`,
   keyed by `default_routing_policy().id` — the handler does not require a
   caller to pass a snapshot explicitly; promotion via `POST
   /v2/evals/{namespace}/{name}/publish` changes subsequent `/v2/select`
   decisions transparently.
9. **SDK contract surface** (`backend/sdk/contracts.py`) re-exports
   `AgentScoreAggregate`; `SDK_CONTRACT_VERSION` bumped 1.4.0 → 1.5.0
   (additive/MINOR — `ScoreSnapshot` gained fields with defaults, no existing
   export changed shape).

See ADR-009's E5-S4 amendment for the Evaluation Service side of this split:
aggregating persisted `EvalResult`s into a `ScoreSnapshot` and durably
publishing it (`EvaluationService.publish_snapshot`).
