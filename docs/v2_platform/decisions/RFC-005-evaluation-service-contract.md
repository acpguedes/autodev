# RFC-005 — Evaluation Service Contract (`eval.yaml`, `Evaluator`)

- **Status:** Accepted
- **Epic:** E5-S3
- **Date:** 2026-07-05
- **Related:** ADR-009 (service boundary), reference §9.4; see RFC-004 for how
  scores eventually feed routing (E5-S4, future story)

## Summary

Defines the typed `eval.yaml` spec an Eval author writes, the pluggable
`Evaluator` extension point (`deterministic` / `llm-as-judge` / custom) the
**Evaluation Service** dispatches to, and the immutable, versioned
`EvalResult` it persists. This is independent of the Router/Selector contract
(E5-S1/S2, RFC-004): the Evaluation Service scores what an agent/strategy
already produced; it does not itself route or select anything.

## Motivation

Reference §9.4 requires evals to run offline (datasets, golden sets,
LLM-as-judge, rubrics, deterministic sandbox checks) and online (feedback,
A/B, canary), persisting results and publishing score snapshots the (not yet
built) Selector reads. That requires a versioned, testable contract for the
spec format and the scorer extension point — this RFC.

## Contract surface

- **Spec (`backend/evals/contract.py`, parsed by `backend/evals/spec.py`):**
  `EvalSpec` (`target`, `mode`, `dataset`, `evaluators`, `metrics`, `gate`,
  `online`) and its nested dataclasses (`EvalTarget`, `EvalDataset`,
  `EvaluatorSpec`, `RubricCriterion`, `MetricsSpec` + per-dimension specs,
  `GateSpec`, `OnlineConfig`, `ABTestSpec`). `validate_eval_spec`/
  `load_eval_spec` mirror `validate_reasoning_strategy_manifest`/
  `load_reasoning_strategy_manifest` (E4-S1).
- **Evaluator extension point:** `Evaluator` (`score(spec, case, provider) ->
  EvalCaseScore`), dispatched by `kind` through a `dict[str, Evaluator]` in
  `EvalRunner` — not a versioned registry like `ReasoningStrategyRegistry`,
  because evaluator *kinds* are not independently SemVer-versioned plugins;
  they are a small, open set an eval spec selects by string.
- **Built-in kinds (`backend/evals/runner.py`):** `DeterministicEvaluator`
  (evaluates `check`, a boolean expression, via the safe AST-whitelist
  evaluator in `backend/evals/expressions.py` — never `eval()`) and
  `LLMJudgeEvaluator` (prompts an `LLMProvider`, the same protocol
  `backend.reasoning.service.ReasoningService` uses, for a rubric-weighted
  score).
- **Result (`backend/evals/results.py`):** `EvaluatorResult` (per-evaluator
  mean + per-case scores), `RunMetrics` (quality per evaluator id, cost/latency
  mean+p95), `EvalResult` (the persisted, immutable record, keyed by
  `eval_id`+`eval_version`+`run_id`).
- **Versioning:** `EVAL_CONTRACT_HOST_API = ">=2.0 <3.0"`; the SDK contract
  export (`backend/sdk/contracts.py`) is bumped to `1.3.0`.

## Contract rules

1. A deterministic `check`/gate `fail_if` expression is evaluated only through
   the safe expression evaluator — no `eval()`/`exec()` anywhere in the path.
2. An `Evaluator` never raises past a single case: an unresolvable check or an
   invalid/incomplete judge response scores that case `0.0` with an `error`/
   `breakdown` detail, so one bad case cannot abort a whole dataset run.
3. `EvalResult`s are immutable and versioned: `(eval_id, eval_version, run_id)`
   is a durable-store uniqueness constraint (never an `UPDATE`); a re-run
   always produces a new `run_id`.
4. `mode: online` accepts and persists `online.publish_scores`/`online.ab_test`
   as a typed record; it executes no traffic-splitting/A-B/canary logic in
   this story (see ADR-009).

Contract tests (`backend/tests/test_evals_contract.py`,
`backend/tests/test_evals_runner.py`) validate spec parsing, both built-in
evaluator kinds, gate pass/fail, result round-tripping/immutability, and that
a custom `Evaluator` kind plugs in without touching `backend/evals/runner.py`.

## Rejected alternatives

- **Versioned `EvaluatorRegistry` (SemVer, host-API check), mirroring
  `ReasoningStrategyRegistry`** — rejected for this story: evaluator kinds are
  not independently distributed/versioned plugins the way reasoning
  strategies are; a flat `dict[str, Evaluator]` dispatch satisfies the
  "pluggable" functional DoD with far less machinery. Revisit if evaluator
  kinds are ever packaged/distributed independently.
- **Reuse `backend.reasoning.contract.TraceEvent` directly** — rejected; the
  Evaluation Service defines its own identically-shaped `TraceEvent` so it
  does not depend on the Reasoning Engine module for an unrelated
  cross-cutting concern. See ADR-009.
- **`eval()`/`exec()` for `check`/`fail_if`** — rejected outright: an eval spec
  is often authored by whoever owns a dataset, not necessarily a trusted core
  maintainer; arbitrary code execution in a scoring path is an unacceptable
  security surface. A restricted AST-whitelist evaluator was built instead.

## Rollout

E5-S3 lands the spec/contract, the two built-in evaluator kinds, the runner,
the service, and dual-backend (SQLite/Postgres) persistence. E5-S4 builds the
score-snapshot publication and the Selector feedback loop referenced in
RFC-004, plus real online A/B/canary execution.
