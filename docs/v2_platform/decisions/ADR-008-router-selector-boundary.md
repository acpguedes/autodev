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
