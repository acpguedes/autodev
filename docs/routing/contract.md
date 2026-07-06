# Router and Selector Contract (E5-S1, E5-S2)

The **Router** classifies a task's intent from the run state (message,
session, repository context) and produces a **Route Decision**: the task
type, the suggested execution path, and applicable constraints. It runs
pluggable **Router** implementations behind one typed, versioned contract at
the `router` extension point, without any strategy-specific code in the core.

This page is the practical guide. The authoritative specification is
`docs/architecture/v2_platform_reference.md` §9.1-9.3, §9.6-9.7; the decisions
are RFC-004 and ADR-008.

## The contract

A Router implements `backend.routing.contract.RouterPlugin`:

```python
from typing import Any, Mapping
from backend.routing import RouteDecision, RouteRequest, RoutingPolicy

class MyRouter:
    def route(
        self, req: RouteRequest, policy: RoutingPolicy, *, context: Mapping[str, Any] | None = None
    ) -> RouteDecision:
        ...
```

Unlike the Reasoning Strategy contract (ADR-007), `RouterPlugin.route` is
**synchronous** — routing is a cheap, deterministic classification with a p95
< 150 ms target (reference §9.7), not an LLM-mediated run.

`context` is an additive keyword-only parameter every implementation must
accept (defaulting to `None`): it carries caller-supplied signals not yet
modeled on `RouteRequest` (e.g. an upstream classifier's `intent` hint).
`RoutingService.route()` forwards it to whatever `RouterPlugin` it wraps
unconditionally — there is no special-casing of the built-in `Router` — so a
fully custom Router implementation gets the same signals the built-in one
does (see ADR-008).

## Classifying a request

```python
from backend.routing import (
    ContextDigest, ContextSignals, RouteInput, RouteRequest,
    RoutingService, TraceEvent, default_routing_policy,
)

events: list[TraceEvent] = []
service = RoutingService(default_routing_policy(), on_event=events.append)

req = RouteRequest(
    schema_version="1.0",
    session_id="s1",
    run_id="r1",
    input=RouteInput(text="update the README with new install steps"),
    context_digest=ContextDigest(repo="acme/widgets", signals=ContextSignals(has_tests=True)),
)
decision = service.route(req)
# decision.task_type == "documentation-update"
# decision.path == ("navigator", "analyzer", "responder")
# events[0].name == "router.decision.recorded"
```

`RoutingService.route` accepts an optional `context` mapping layered on top of
the signals derived from the request (e.g. an `intent` hint from an upstream
classifier), and always emits exactly one `router.decision.recorded` trace
event per call — this is what makes every `RouteDecision` traceable (E5-S1
DoD).

## The pipeline (`router:` policy section)

`RoutingPolicy.router` is an ordered pipeline of stages, evaluated with
**short-circuit by confidence**: the first stage whose result confidence
meets its `confidence_floor` wins; otherwise the pipeline cascades to the
next stage, and finally to `router.default` if nothing matches.

```yaml
router:
  pipeline:
    - kind: rules
      confidence_floor: 0.0
      rules:
        - when: {"input.text": "~=/(?i)\\b(doc|readme|changelog)\\b/"}
          set: {task_type: documentation-update, intent: docs, path: [navigator, analyzer, responder]}
        - when: {"context.signals.has_tests": true, "intent": "validate"}
          set: {task_type: validation-only, intent: validate, path: [navigator, validator, responder]}
    - kind: embeddings
      dataset: autodev/intents@2026-06
      threshold: 0.72
    - kind: llm-router
      model: provider/router-small
      max_cost_usd: 0.01
      only_if_confidence_below: 0.72
  default:
    task_type: existing-repo-change
    intent: unspecified
    path: [navigator, analyzer, architect, coder, devops, validator, responder]
```

Only `kind: rules` is executed in E5-S1. `kind: embeddings` (pgvector/E7) and
`kind: llm-router` (LLM-as-router) parse into typed specs
(`RouterEmbeddingsStageSpec`, `RouterLLMStageSpec`) but raise
`NotImplementedError` if the pipeline actually reaches one — inject a
concrete `EmbeddingsRouterStage`/`LLMRouterStage` via `Router(embeddings_stage=...,
llm_router_stage=...)` to implement them without touching the core pipeline
executor.

**Known E5-S1 limitation:** `threshold` (embeddings) and
`only_if_confidence_below` (llm-router) are validated at parse time, but the
core pipeline loop does not itself track "best confidence seen so far" across
stages to decide whether an `llm-router` stage should even be invoked — a
`resolve()` implementation is responsible for applying its own `spec` fields
(e.g. only returning a result when a similarity score exceeds
`spec.threshold`). Confidence-aware stage *gating* (skipping a stage outright
based on prior stages' confidence) is left for when these stages get a real
implementation, since both are stubs by design this story.

### Rule predicates (`when`)

A rule's `when` is a mapping of dotted signal name to an expected literal or
an operator expression, all AND-combined:

| Signal | Meaning |
| --- | --- |
| `input.text` | The request's free-text input |
| `input.attachments` | Attachment URIs |
| `context.repo` | Repository identifier from `context_digest` |
| `context.signals.has_tests` | Whether the repo has a test suite |
| `context.signals.languages` | Detected repo languages |
| *(caller-supplied)* | Any extra key passed via `context=...` |

Supported operators (reused from `backend.reasoning.selection`'s
`_match_value`/`_compare`/`_coerce` approach, plus a routing-specific regex
operator): `>=`, `<=`, `==`, `>`, `<` for numeric/string comparison, and `~=`
for a regex search against the stringified actual value (an optional
surrounding `/.../` is stripped before compiling). A bare literal (no
operator prefix) is an exact match.

A `~=` pattern is pre-compiled at policy-validation time
(`backend.routing.policy_parsing._validate_when_predicates`) — a malformed
regex is a `validate_routing_policy`/`load_routing_policy` error, not a rule
that silently never matches once a bad policy is already loaded. Likewise, a
rule's `set.path` must be a list of strings and an optional `set.constraints`
must have the same shape as `router.constraints` (`max_cost_usd` non-negative,
`latency_class` one of `interactive`/`batch`) — both are checked at parse
time rather than surfacing as a request-time crash.

### Pluggability

The DoD requires a custom rule or policy to change the routed decision
without core changes — this is exactly what the declarative pipeline gives
you: build a different `RoutingPolicy` (or just a different `rules` stage)
and pass it to `RoutingService`; no `Router`/`RoutingService` code changes.

## Policy document

`routing-policy.yaml` (parsed by `backend.routing.policy`) governs the
`router:` pipeline and the `selector:` pipeline (both fully implemented) plus
placeholder `guardrails:` and `fallback:` sections — parsed into `raw: dict`
wrappers but unused until a later E5 story defines their typed shape on the
*same* `RoutingPolicy` object (reference §9.3, §9.6).

`backend.routing.policy.default_routing_policy()` builds a permissive default
that generalizes the v1 precursor's hardcoded `_ROUTE_MAP`
(`backend/orchestrator/routing.py`) into the new declarative format:
documentation updates, validation-only runs, and DevOps changes as `rules`,
falling back to the full agent pipeline as `router.default` — plus a default
`selector:` pipeline (match on `required_capabilities` or every registered
agent if none are given, `minimize_cost`, tie-break `lowest_cost`).

## Packaging as a plugin

E5-S1/E5-S2 do not ship a `router-plugin.yaml`/`selector-plugin.yaml` manifest
format (unlike `reasoning-strategy.yaml`, E4-S1) — the pluggable surface for
these stories is the declarative `RoutingPolicy` pipelines plus the
`RouterPlugin`/`SelectorPlugin` Protocols for callers who want to supply an
entirely custom classifier/selector object. Manifest-based plugin packaging,
if needed, is left to a later story.

## Selector Contract (E5-S2)

The **Selector** receives a Router's `RouteDecision` plus
`required_capabilities` and a run `budget`, matches candidates in the **Agent
Registry** (E2, `backend.agents.registry_v2.AgentRegistry`), and produces a
**Select Decision**: the chosen agent/version/model/Reasoning Strategy (E4),
its resolved budget, and up to 3 cascade-fallback candidates.

```python
from backend.agents.registry_v2 import AgentRegistry
from backend.routing import RoutingPolicy, ScoreSnapshot, SelectDecision, SelectRequest

class MySelector:
    def select(
        self, req: SelectRequest, policy: RoutingPolicy, registry: AgentRegistry, scores: ScoreSnapshot | None = None
    ) -> SelectDecision:
        ...
```

Synchronous, mirroring `RouterPlugin` (ADR-008): capability/cost-aware
matching is in-process registry reads, no LLM/tool mediation to await.

### Selecting a candidate

```python
from backend.agents.registry_v2 import AgentRegistry
from backend.routing import RouteConstraints, RouteDecision, RoutingService, SelectBudget, SelectRequest, TraceEvent, default_routing_policy

registry = AgentRegistry()  # or a store-bound instance for tests
events: list[TraceEvent] = []
service = RoutingService(default_routing_policy(), on_event=events.append)

req = SelectRequest(
    schema_version="1.0",
    route=RouteDecision(
        schema_version="1.0", task_type="existing-repo-change", intent="add-feature",
        path=("navigator", "coder", "responder"), confidence=1.0,
        constraints=RouteConstraints(max_cost_usd=0.05, latency_class="interactive"),
        rationale="routed to the coder path",
    ),
    required_capabilities=("code.implementation",),
    budget=SelectBudget(tokens=0, cost_usd=0.0, time_s=0),  # 0 = unconstrained
)
decision = service.select(req, registry=registry)
# events[-1].name == "selector.decision.recorded"
```

`POST /v2/select` exposes the same flow over HTTP (see
`backend/api/routers/routing.py`), returning **422** if no registered agent
satisfies `required_capabilities` under the active policy
(`backend.routing.selector.NoEligibleAgentError`, a fail-closed default).

### The pipeline (`selector:` policy section)

Unlike the Router's `rules` stage (first-match-wins by confidence), the
selector pipeline is a **sequential transform**: each stage narrows or
reorders the candidate list the previous stage produced.

```yaml
selector:
  pipeline:
    - kind: capability-matching
      require_all: true
    - kind: cost-aware
      objective: minimize_cost         # minimize_cost | minimize_latency | maximize_quality
      respect: {run_budget: true, tenant_quota: true}
    - kind: score-weighted             # no-op until E5-S4 wires a real score snapshot
      weights: {quality: 0.6, cost: 0.25, latency: 0.15}
  tie_breaker: lowest_cost
```

- **`capability-matching`** — client-side set intersection (`require_all:
  true`) or union (`false`) over `AgentRegistry.find_by_capability`, called
  once per (deduplicated) required capability and keyed by `(agent_id,
  version)` (ADR-008). An empty `required_capabilities` matches every
  candidate already in the pool (or every registered agent, if it runs
  first).
- **`cost-aware`** — filters out candidates whose own
  `AgentBudgets` cannot fit the run's `budget` (`respect.run_budget`; a `0` in
  any `SelectRequest.budget` field means unconstrained for that dimension),
  then its `objective` drives the final ranking. `respect.tenant_quota` is
  parsed but **not enforced** — tenant quotas are E11 (multi-tenancy), not
  built yet; only the run's own budget is respected.
- **`score-weighted`** — a **documented no-op passthrough**: no Evaluation
  Service score snapshot store exists yet (E5-S4 wires it in). The stage is
  still fully typed (`ScoreSnapshot`, the `weights` spec) so a future story
  doesn't need to redesign the pipeline signature; if a `ScoreSnapshot` is
  supplied its `snapshot_id` is recorded as `SelectDecision.score_basis` for
  forward audit, but its scores do not affect ordering today.
- **`tie_breaker: lowest_cost`** — applied last, for full determinism: given
  the same registry state, policy, and request, the same `SelectDecision`
  comes out every run. Ties are broken by ascending cost, then descending
  agent version (prefer newer), then ascending `agent_id` — a total order,
  since the registry's primary key is `(agent_id, version)`.

`model`/`reasoning_strategy` are read from the chosen candidate's
`AgentManifest.policy` free-form mapping (`policy.model`,
`policy.reasoning_strategy`; no typed field exists on the manifest for
either), falling back to platform defaults when absent — see ADR-008's E5-S2
amendment.

### Pluggability

Exactly like the Router: pass a custom policy (a different `selector:`
pipeline) to change which candidate wins, or pass an entirely custom
`SelectorPlugin` to `RoutingService(policy, selector=...)` — no
`Selector`/`RoutingService` code changes required.
