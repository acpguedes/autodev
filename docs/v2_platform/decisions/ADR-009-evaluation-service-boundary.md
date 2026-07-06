# ADR-009 — Evaluation Service Boundary and Scope

- **Status:** Accepted
- **Date:** 2026-07-05
- **Related:** RFC-005 (contract surface), reference §9.4

## Context

E5-S3 introduces the **Evaluation Service** (reference §9.4). Four boundary
questions had to be settled before implementation: (1) how much of "offline
vs. online" evals to actually build; (2) where dataset case data comes from;
(3) whether to reuse the Reasoning Engine's `TraceEvent`/`on_event` pattern
by importing its types or by mirroring the pattern independently; and (4) how
results are persisted given the "versioned and reproducible" NFR.

E5-S3's functional DoD is narrower than the full reference §9.4 vision: "an
eval runs over a dataset and produces a score per rubric; the Evaluator is
pluggable." Full online A/B/canary traffic-splitting and the Selector feedback
loop are reference §9.5/§9.6 concerns assigned to E5-S4, a separate story.

## Decision

1. **Offline execution is fully built; online is a typed-but-minimal stub.**
   `EvaluationService.run_offline` executes every declared evaluator over
   caller-supplied cases, computes metrics, evaluates the gate, and persists
   an `EvalResult`. `EvaluationService.register_online` accepts and durably
   stores the `online.publish_scores`/`online.ab_test` shape from a spec but
   runs no traffic-splitting, canary, or promotion logic — that is E5-S4's
   scope, once a Selector/routing-policy consumer of scores exists to
   promote/revert against.

2. **Dataset-case loading is out of scope; callers supply `EvalCase`s
   directly.** No Context/RAG Service (E7) or golden-set store exists yet to
   resolve `dataset.ref`/`split` into concrete rows. `dataset.ref`/`split`/
   `size` are recorded on every result for audit and reproducibility, but the
   runner scores whatever `EvalCase` objects it is given. A dataset loader is
   a natural, additive extension point for a future story once E7 exists.

3. **`TraceEvent`/`on_event` pattern is mirrored, not imported.** The
   Evaluation Service defines its own `backend.evals.contract.TraceEvent`
   (same `sequence`/`name`/`payload`/`timestamp` shape and `on_event` sink as
   `backend.reasoning.contract.TraceEvent`) rather than importing the
   Reasoning Engine's type. Rationale: Evals and Reasoning are sibling
   subsystems under E5/E4 respectively; the tracing pattern is a shared
   *convention* (and, eventually, an Event Bus (E9) hook), not a shared
   *dependency* — importing across epic boundaries for an identically-shaped
   dataclass would create a coupling with no corresponding architectural
   relationship. Both should converge on a single Event Bus event envelope
   when E9 lands; until then, duplication is cheaper than the wrong coupling.

4. **Results are immutable and versioned via a uniqueness constraint, not
   application-level convention.** `eval_results` (added additively to both
   `SQLiteStore` and `PostgresStore`, selected via `get_store()`/
   `DATABASE_URL` per ADR-001) enforces `UNIQUE(eval_id, eval_version,
   run_id)` at the database layer — a re-run with a colliding `run_id` fails
   loudly (`IntegrityError`) rather than silently overwriting history. Every
   `EvaluationService.run_offline`/`register_online` call generates a fresh
   `run_id` (UUID4) unless the caller explicitly forces one.

5. **Evaluator dispatch is a flat, unversioned `dict[str, Evaluator]`,** not a
   `ReasoningStrategyRegistry`-style SemVer registry (see RFC-005's rejected
   alternatives). Evaluator kinds are a small, open set selected by string in
   an eval spec, not independently packaged/distributed plugins today.

## Consequences

- (+) The functional DoD (pluggable Evaluator, per-rubric scoring, versioned
  results) is fully met with a small, well-tested surface.
- (+) No premature online A/B/canary infrastructure is built against a
  Selector that does not exist yet (E5-S4 dependency is explicit).
- (+) Immutability is enforced structurally (a DB constraint), not just by
  convention/code review.
- (−) `dataset.ref` is presently inert beyond being recorded for audit —
  callers (CI jobs, test harnesses) must supply case payloads themselves until
  a dataset loader exists.
- (−) `TraceEvent` is duplicated (once in `backend.reasoning.contract`, once
  in `backend.evals.contract`) until the Event Bus (E9) unifies both onto one
  envelope type.
- Contract tests (`backend/tests/test_evals_contract.py`,
  `backend/tests/test_evals_runner.py`) gate the Evaluator protocol, gate
  evaluation, and result immutability against this boundary.

## Rollback plan

The `eval_results` table/columns are additive; dropping them (and the
`backend/evals/` package) reverts cleanly with no impact on existing tables.
No other subsystem depends on the Evaluation Service yet (E5-S4 will be the
first consumer), so this is fully revertible without a migration for
dependents.

## References

- RFC-005, `docs/architecture/v2_platform_reference.md` §9.4, ADR-001
  (PostgreSQL as default production state store), ADR-007 (the Reasoning
  Engine's analogous `on_event`/boundary decisions this ADR mirrors).

## Amendment (E5-S4)

E5-S4 is "E5-S4 will be the first consumer" materializing: it adds
`EvaluationService.publish_snapshot`, which aggregates persisted
`EvalResult`s into a versioned `ScoreSnapshot` (`backend.routing.contract`)
and durably publishes it. Deciding whether that snapshot is *promoted* for a
routing policy is explicitly **not** this service's concern — see ADR-008's
E5-S4 amendment for `RoutingFeedbackService`, which owns that decision.

1. **Aggregation boundary: `publish_snapshot` groups by `agent_id`, nothing
   else.** `EvalResult` gained an additive `agent_id: str = ""` field
   (populated from `spec.target.agent_id` in `run_offline`; `""`/`"unknown"`
   for results persisted before this field existed, so old rows are not
   dropped, just bucketed together) — this is the only new column on the
   already-immutable `eval_results` table. Per-agent quality is the mean of
   each contributing run's per-evaluator mean scores; cost/latency use
   `RunMetrics.cost_usd_mean`/`latency_p95_seconds`. No new dataset/case
   concept is introduced; this reuses `list_results` unchanged.
2. **Snapshot storage is additive and mirrors `eval_results`'s immutability
   convention, not a new mechanism.** Two new tables, `score_snapshots`
   (one immutable row per `snapshot_id`) and `score_snapshot_promotions`
   (append-only audit log of every promotion decision), added identically to
   `SQLiteStore` and `PostgresStore` — same "additive table/method on both
   adapters" pattern point 4 of the original decision established for
   `eval_results`. `score_snapshot_promotions` intentionally lives alongside
   `score_snapshots` (both are new, both are Evaluation-Service-adjacent
   persistence concerns) even though the *decision logic* that writes to it
   lives in `backend.routing.feedback` — the store methods themselves are
   boundary-agnostic plumbing, not policy.
3. **Publishing raises `EvalError` (fails closed) when there is nothing to
   aggregate**, rather than persisting an empty/meaningless snapshot —
   consistent with this ADR's existing "fail loud, not silent" posture for
   `run_offline`/`register_online`'s `EvalResultConflictError`.
4. **`publish_snapshot` emits `eval.scores.published`** via the same
   `on_event`/`TraceEvent` mirroring convention (decision 3 above) — one more
   event alongside `eval.run.*`, not a new tracing mechanism.
5. **No online A/B/canary traffic-splitting is built here either** — decision
   1's scope boundary still holds. `publish_snapshot` aggregates whatever
   `EvalResult`s are already persisted (offline or online-registered); actual
   variant/control comparison and promotion is `RoutingFeedbackService`'s job
   (ADR-008 amendment), reusing `ABTestSpec.promote_if`/`min_samples` as pure
   data, not by adding an A/B execution engine to the Evaluation Service.

## Rollback plan (E5-S4 addendum)

`score_snapshots`/`score_snapshot_promotions` and the `agent_id` column are
additive; dropping them reverts cleanly. `backend.routing.feedback` is the
only consumer of the new store methods — removing it alongside the tables
leaves E5-S1/S2/S3 behavior fully intact (the `score-weighted` selector stage
falls back to its documented no-op passthrough when no snapshot is ever
supplied, exactly as before E5-S4).
