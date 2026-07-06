# RFC-004 — Router & Selector Contract (`router`, `selector`)

- **Status:** Accepted
- **Epic:** E5-S1 (Router), E5-S2 (Selector, follow-up)
- **Date:** 2026-07-05
- **Related:** ADR-008 (router/selector boundary), reference §9.2-9.3

## Summary

Defines the typed, SemVer-versioned contract the **Router** implements to plug
into the task-classification path at the `router` extension point, and the
`RouteRequest`/`RouteDecision` data contract it produces. Reference §9.2
documents `RouteRequest`/`RouteDecision` and `SelectRequest`/`SelectDecision`
as one contract section, so this RFC also fixes the `SelectRequest`/
`SelectDecision` shape and the `SelectorPlugin` Protocol for E5-S2 to implement
against directly — E5-S2 does not need a second RFC for that surface.

## Motivation

Reference §9.1 splits "what/where" (Router) from "with what" (Selector) as a
deliberate separation of concerns, both versioned extension points. The v1
precursor (`SupervisorPolicy`/`RunTypeRouter` in
`backend/orchestrator/routing.py`) hardcodes an intent-to-agent-order mapping
(`_ROUTE_MAP`) with no declarative policy, no confidence, and no trace — it is
not wired into the default `/chat` path. E5-S1 replaces it functionally with a
typed contract and a declarative, pluggable pipeline, without touching the v1
module (still used as-is elsewhere; out of scope for this story).

## Contract surface (`backend/routing/contract.py`, `backend/routing/policy.py`)

- **Data types:** `RouteRequest` (`schema_version`, `session_id`, `run_id`,
  `input: RouteInput`, `context_digest: ContextDigest | None`), `RouteDecision`
  (`schema_version`, `task_type`, `intent`, `path`, `confidence`,
  `constraints: RouteConstraints`, `rationale`), `RouteConstraints`
  (`max_cost_usd`, `latency_class`), `TraceEvent` (local, shape-identical to
  `backend.reasoning.contract.TraceEvent` — see ADR-008 for why it is not
  imported).
- **Protocol:** `RouterPlugin.route(req, policy, *, context=None) -> RouteDecision`
  — synchronous (see ADR-008), unlike the async `ReasoningStrategy.run`.
  `context` is an additive keyword-only parameter (default `None`) every
  implementation accepts, carrying caller-supplied signals not yet modeled on
  `RouteRequest`; `RoutingService` forwards it uniformly to any conforming
  implementation, with no special-casing of the built-in `Router`.
- **Policy:** `RoutingPolicy` (`router: RouterPipelineSpec`, plus placeholder
  `selector`/`guardrails`/`fallback` sections carrying `raw: dict` for E5-S2+)
  with a `router.pipeline` of `rules` (fully implemented), `embeddings` and
  `llm-router` (typed, `NotImplementedError` stubs).
- **Versioning:** `ROUTING_CONTRACT_HOST_API = ">=2.0 <3.0"`; the SDK contract
  export (`backend/sdk/contracts.py`) is bumped to `1.3.0` (additive/MINOR —
  new `RouterPlugin` export, no existing contract changed).

## Selector surface fixed for E5-S2 (not implemented this story)

Per reference §9.2, the Selector contract this RFC fixes for the follow-up
story:

```python
SelectRequest:
  schemaVersion: "1.0"
  route: RouteDecision
  required_capabilities: [string]
  budget: {tokens: int, cost_usd: number, time_s: int}

SelectDecision:
  schemaVersion: "1.0"
  agent_id: string
  agent_version: string
  model: string
  reasoning_strategy: string
  budget: {tokens: int, cost_usd: number, time_s: int}
  fallbacks: [ {agent_id, model, reasoning_strategy} ]
  score_basis: string

class SelectorPlugin(Protocol):
    def select(self, req: SelectRequest, policy: SelectionPolicy,
               registry: AgentRegistry, scores: ScoreSnapshot) -> SelectDecision: ...
```

E5-S2 implements `SelectRequest`/`SelectDecision`/`SelectorPlugin` and the
`selector:` policy section against this fixed shape; capability matching is
client-side intersection over `AgentRegistry.find_by_capability` (ADR-008),
not a new registry method.

## Contract rules

1. `RouterPlugin.route` is a pure function of `(req, policy)` — no side
   effects, no implicit state between calls (a Router is stateless, mirroring
   rule 2 of RFC-003 for Reasoning Strategies).
2. Every `RouteDecision` a `RoutingService` produces is recorded to the trace
   sink as a `router.decision.recorded` event — the decision-trace DoD.
3. The pipeline evaluates stages in declared order with short-circuit by
   confidence: the first stage whose result meets its `confidence_floor`
   wins; otherwise cascade to the next stage, finally to `router.default`.
4. `rationale` is a separate, human-readable field from any structured
   metadata (repository working-style convention: user-visible summaries kept
   apart from control metadata).

Contract tests (`backend/tests/test_routing_contract.py`,
`backend/tests/test_routing_router.py`) validate the rules-pipeline
implementation against these rules; they are mandatory for the extension
point (E12).

## Rejected alternatives

- **Free-form boolean-expression `when` (e.g. `"context.signals.has_tests and
  intent == 'validate'"`)** — reference §9.3's illustrative `routing.yaml`
  shows a richer expression DSL with `and`/`or` and inline regex literals.
  Rejected for E5-S1 in favor of a dict-based `when` (dotted key → literal or
  operator expression), reusing the same predicate-matching approach as
  `backend.reasoning.selection` plus one addition (`~=` regex). A full
  boolean-expression parser is a larger, separable investment better justified
  once a real policy author needs `and`/`or` combinators beyond AND-of-keys;
  it can be added as a new operator/stage kind without breaking this contract.
- **Async `RouterPlugin.route`** — rejected unlike the Reasoning Strategy
  contract (ADR-007): routing has no LLM/tool mediation to await on the
  primary path, and the p95 < 150 ms NF target (reference §9.7) argues for a
  synchronous, allocation-light call. The `llm-router` stage stub can still be
  backed by an async implementation internally (via `asyncio.run` at its own
  boundary) without forcing the whole contract async.
- **Importing `backend.reasoning.contract.TraceEvent`** — rejected; see
  ADR-008. A local, shape-identical `TraceEvent` avoids an upstream
  (Router/E5) → downstream (Reasoning/E4) module dependency that does not
  reflect the pipeline's actual data flow (Router → Selector → Agent Runtime +
  Reasoning Engine, reference §9.1 diagram).

## Rollout

E5-S1 lands the Router contract, the rules-pipeline executor, the
`RoutingPolicy` model (with E5-S2 placeholders), the tracing service, and
`POST /v2/route`. E5-S2 implements the Selector against the `SelectRequest`/
`SelectDecision`/`SelectorPlugin` shape fixed above and replaces the
`selector:` placeholder's internals; E5-S3/E5-S4 add the Evaluation Service
and the closed feedback loop.
