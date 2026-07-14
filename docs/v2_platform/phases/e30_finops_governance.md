# E30 — FinOps & Autonomy Governance

**Wave:** v2.2 — Concept Integration (S1/S2 may start once E2/E3 are stable;
dashboards land with/after E11, which this epic extends, not duplicates).
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E2 (per-call metering), E3 (budget propagation, ADR-006),
E5 (Selector), E11 (observability/governance surfaces — E30 feeds them)
**Enables:** predictable spend for every wave (the #1 enterprise adoption
blocker of 2026), E13 (marketplace billing readiness), E24/E17 cost panels
**Canonical source:** `docs/architecture/v2_platform_reference.md` §23.6,
§18.7.22; RFC-008

## Objective

Make cost a **first-class, legible, enforceable resource**: pre-run cost
estimation surfaced before execution (per-operation price legibility),
hierarchical fail-closed budget caps (tenant → team/project → run → task)
with checkpoint ceilings and kill switches, draft-vs-final execution tiers
as routing policy (cheap fast pass → escalate → verified final), and
per-surface metering (API/UI/CLI/MCP) so one engine serves many clients with
independent accounting.

## Key result

Before approving a plan or harness run, an operator sees an estimated cost
range (tokens/currency/wallclock) with confidence; during execution,
hierarchical caps stop overspend fail-closed at every level (a runaway retry
loop hits its checkpoint ceiling, not the credit card); routing policy runs
draft iterations on cheap models and reserves strong models for final
verified passes; and per-surface dashboards show who spent what, where.

## Prior art (condensed)

Enterprise cost reality (agentic tasks ≈1000x single-turn tokens; widespread
budget blowouts; spend controls now table stakes), HeyGen (published unit
price per operation before running; separate billing pools per integration
surface), Google Flow (per-generation credit deduction scaled by
model+settings; coarse credits frustrate users — meter finer), Replit-class
runaway checkpoint billing (the failure mode S2 prevents), Suno/HeyGen
draft→final tier pipelines, gateway/control-plane convergence (central
broker enforcing budgets/audit — validates §2.13). KV-cache economics
(cached input ~10x cheaper) via E26. Sources in RFC-008.

## Stories

### E30-S1 — Pre-run cost estimation & price legibility

Subtasks:
- `E30-S1-T1`: `cost_estimator` extension-point kind (RFC-001, additive) —
  given a task/plan/harness config (model mix, expected iterations,
  context strategy), returns an estimate range + confidence; reference
  estimator uses historical run statistics per task class (State Store)
  and provider price tables.
- `E30-S1-T2`: `/v2/estimates` (§14.1) — estimate for a plan step, flow, or
  harness run before start; estimates persisted and later joined with
  actuals (estimate-vs-actual accuracy tracked as a metric).
- `E30-S1-T3`: surfacing — plan approval (E16-S2) and harness start carry
  the estimate; UI shows range + confidence (E17/E24 panels consume);
  provider price tables are operator-configurable (self-hosted reality:
  prices vary).

| Criterion | Detail |
| --- | --- |
| Functional | Every plan-approval and harness-start surface shows an estimate range before execution; estimate-vs-actual is queryable per task class; estimator plugins pass the contract test |
| Non-functional | Estimation itself is cheap (no LLM call in the reference estimator); price tables tenant-configurable |
| DoR (specific) | RFC-008 accepted; epic ADR (estimation model & metering semantics) filed |
| DoD (specific) | Estimate/actual join tests + accuracy metric; `docs/finops/estimation.md` |
| Dependencies | E2-S4 (metering), E16-S2, E1 |

### E30-S2 — Hierarchical budget caps, ceilings & kill switches

Subtasks:
- `E30-S2-T1`: budget hierarchy — caps at tenant, team/project, run, and
  task level; child budgets always ≤ remaining parent budget (ADR-006
  semantics extended upward); currency and token denominations both
  supported; period caps (day/week/month) at tenant/team level.
- `E30-S2-T2`: checkpoint ceilings — iteration-producing constructs
  (harness loops, retry policies, candidate sets) carry a max-checkpoint/
  max-iteration ceiling independent of token budgets, preventing
  many-small-steps runaway; exhaustion yields the typed stop state
  (`max_budget` / `max_iterations`), never silent continuation.
- `E30-S2-T3`: kill switches — operator-facing immediate stop at any
  hierarchy level via `/v2` (tenant-wide freeze downward); stops are
  evented (`cost.limit.hit`, `cost.killed`), audited, and resumable where
  the run state allows (E3 checkpoints).

| Criterion | Detail |
| --- | --- |
| Functional | A child can never spend past its parent (property test across the hierarchy); a crafted infinite-retry fixture stops at its ceiling with the typed state; a tenant freeze halts all descendant runs and is audited |
| Non-functional | Enforcement fail-closed on metering lag (reserve-then-settle, not spend-then-check); overhead per call bounded |
| DoR (specific) | E30-S1 available; ADR-006 reviewed (extension is additive upward) |
| DoD (specific) | Hierarchy property tests, runaway fixture, freeze test; `docs/finops/budgets.md` |
| Dependencies | E2, E3 (ADR-006), E8, E11 (audit sink, additive) |

### E30-S3 — Draft-vs-final execution tiers

Subtasks:
- `E30-S3-T1`: Selector policy vocabulary gains `tier: draft | final`
  (additive MINOR per RFC-004) — `draft` resolves to cheap/fast profiles,
  `final` to strong profiles; tier is declared per flow node, harness
  phase, or candidate set.
- `E30-S3-T2`: escalation policy — harness loop phases default to draft
  iterations with escalation to final on configurable triggers (gate
  near-pass, stagnation, last-mile verification); final verified passes
  always run the full E22/E27 gate set — tiering changes cost, never
  verification rigor.
- `E30-S3-T3`: tier economics — cost/quality per tier tracked per task
  class (joins E30-S1 actuals with gate outcomes) so operators can tune
  tier policies from data; E5 feedback loop (ScoreSnapshots) consumes.

| Criterion | Detail |
| --- | --- |
| Functional | A tiered harness run demonstrably uses cheap profiles for draft iterations and strong profiles for the final pass; verification gates identical across tiers; per-tier cost/quality queryable |
| Non-functional | Tier resolution is Selector policy (no hardcoded model names); works single-provider (tiers degrade to strategy/effort profiles, recorded) |
| DoR (specific) | E30-S1 available; RFC-004 Selector policy reviewed |
| DoD (specific) | Tier-resolution, rigor-invariance, and economics-join tests; `docs/finops/tiers.md` |
| Dependencies | E5, E30-S1, E23 (phase wiring), E27 (gates unchanged) |

### E30-S4 — Per-surface metering & cost observability

Subtasks:
- `E30-S4-T1`: surface attribution — every metered operation carries its
  originating surface (Web UI, CLI, MCP, direct API — from the §2.13
  client identity) so spend is attributable per surface and per client
  credential; optional per-surface budget pools (a surface cap within the
  tenant cap).
- `E30-S4-T2`: cost event family — `cost.*` events (recorded, estimated vs
  actual, limit hits) appended to the run stream; aggregation tables for
  dashboard-speed queries.
- `E30-S4-T3`: dashboards — cost panels (per tenant/team/run/surface/task
  class, estimate-vs-actual, tier economics) delivered through the E11
  operational dashboard surface (this story provides data contracts +
  panels; E11 owns the dashboard shell).

| Criterion | Detail |
| --- | --- |
| Functional | The same operation via MCP vs Web UI lands in different surface pools; dashboards answer "who spent what where" per period; limit hits visible with drill-down to the run |
| Non-functional | Aggregations precomputed (no full-scan dashboard queries); attribution adds no per-call round trip |
| DoR (specific) | E30-S2 available; E11 dashboard surface scoped |
| DoD (specific) | Attribution, pool-cap, and aggregation tests; `docs/finops/metering.md` |
| Dependencies | E30-S2, E9 (events), E11, E15/E17 (panel integration) |

## v1/v2 precursor / starting point

- E2-S4 already meters tokens/cost per call by run+tenant, and ADR-006 gives
  fail-closed run/step budgets — but there is no estimation before
  execution, no hierarchy above the run, no iteration ceilings distinct
  from token budgets, no kill switch, no surface attribution, and no cost
  dashboards. E30 is the layer that turns raw metering into governance.
- E16-S2 plan approval is the natural place estimates surface — the
  approval state machine is consumed unchanged.
- E11 (Not started) owns policies/approvals/dashboards broadly; E30
  deliberately ships the **cost** slice of that surface with data contracts
  E11 can generalize — recorded as a shared-boundary note for both epic
  ADRs.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD plus story-specific DoD above.
- [ ] Contract tests green for estimation, budget hierarchy, tiers, and
      metering attribution.
- [ ] Epic ADR (estimation model & metering semantics; boundary note with
      E11) filed before E30-S1 implementation starts.
- [ ] `cost.*` events documented append-only in the event catalog.
- [ ] `docs/v2_platform/progress.md` updated.
