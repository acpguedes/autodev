# Evaluation Service Spec (E5-S3)

The **Evaluation Service** runs **Evals** — a dataset scored against a rubric,
producing quality/cost/latency metrics and a versioned, immutable result. It
is independent of the Router/Selector (E5-S1/S2): it scores what an
agent/strategy produced, and (in a future story, E5-S4) those scores feed back
into routing/selection policy.

This page is the practical guide. The authoritative specification is
`docs/architecture/v2_platform_reference.md` §9.4; the decisions are RFC-005
and ADR-009.

## The `eval.yaml` spec

```yaml
schemaVersion: "1.0"
id: autodev/eval-coder-bugfix
version: 2.1.0
target:
  kind: agent
  agent_id: autodev/agent-coder
  reasoning_strategy: plan-and-execute   # optional

mode: offline                            # offline | online

dataset:
  ref: autodev/bugfix-golden@2026-06
  split: test
  size: 240

evaluators:
  - kind: deterministic
    id: patch_applies
    check: "patch.dry_run.ok == true"
  - kind: deterministic
    id: tests_pass
    check: "sandbox.tests.exit_code == 0"
  - kind: llm-as-judge
    id: solution_quality
    model: provider/judge-large
    rubric:
      correctness: {weight: 0.5, scale: [0, 1]}
      minimality:  {weight: 0.3, scale: [0, 1]}
      style:       {weight: 0.2, scale: [0, 1]}

metrics:
  quality: {primary: tests_pass, aggregate: mean, min_pass_rate: 0.80}
  cost:    {budget_usd_p95: 0.35}
  latency: {p95_seconds: 45}

gate:
  fail_if: "quality.tests_pass.mean < 0.80 or cost.usd_p95 > 0.35"

online:                     # optional; typed-but-minimal stub (E5-S4 builds the rest)
  publish_scores: true
  ab_test:
    control: {policy: autodev/routing-default@1.4.0}
    variant: {policy: autodev/routing-default@1.5.0-rc}
    traffic: {variant_pct: 10}
    promote_if: "variant.quality >= control.quality and variant.cost <= control.cost"
    min_samples: 500
```

Parse and validate a document with `backend.evals.spec.validate_eval_spec`
(returns an `EvalSpecValidationResult`) or `load_eval_spec(path)` to load
straight from disk.

**Identifier fields inside nested sections use snake_case** (`agent_id`,
`reasoning_strategy`, `min_pass_rate`, `budget_usd_p95`, `fail_if`,
`publish_scores`, `ab_test`, `promote_if`, `min_samples`) — this matches the
reference doc's `eval.yaml` example exactly and differs from the
`schemaVersion`-style camelCase used at the document's top level.

## Dataset-loading scope boundary

Resolving `dataset.ref` into concrete case payloads (a golden-set store) is
**out of scope for this story** — there is no Context/RAG Service (E7) yet to
back it. The runner scores whatever `EvalCase` objects the caller supplies
directly:

```python
from backend.evals import EvalCase

cases = [
    EvalCase(case_id="case-1", payload={
        "patch": {"dry_run": {"ok": True}},
        "sandbox": {"tests": {"exit_code": 0}},
        "candidate": "def fix(): ...",   # judged content for llm-as-judge evaluators
        "cost_usd": 0.12,                # optional, feeds the cost metric
        "latency_seconds": 8.0,          # optional, feeds the latency metric
    }),
]
```

A dataset loader that resolves `dataset.ref`/`split` into `EvalCase` objects is
a natural extension point for a future story; `dataset.ref`/`split`/`size` are
recorded on every result for audit today regardless.

## Running an eval

```python
from backend.evals import EvaluationService, EvalRunner
from backend.evals.spec import validate_eval_spec
from backend.persistence.database import get_store

validation = validate_eval_spec(raw_document)
assert validation.valid, validation.errors
spec = validation.spec

service = EvaluationService(get_store())     # SQLite locally, Postgres in prod (ADR-001)
result = service.run_offline(spec, cases)    # mode must be "offline"

result.gate_passed   # bool
result.metrics       # RunMetrics: per-evaluator quality means, cost/latency p50/p95
result.run_id        # unique per run — re-running never overwrites a prior result
```

`mode: online` specs go through `service.register_online(spec)` instead: it
persists the declared `online.publish_scores`/`online.ab_test` shape as a
typed record but does **not** run anything against live traffic — see ADR-009
for why real A/B/canary execution is deferred to E5-S4.

## The `Evaluator` extension point

```python
from backend.evals import Evaluator, EvalCase, EvalCaseScore, EvaluatorSpec

class MyEvaluator:
    def score(self, spec: EvaluatorSpec, case: EvalCase, provider) -> EvalCaseScore:
        return EvalCaseScore(case_id=case.case_id, evaluator_id=spec.id, score=1.0, details={})

runner = EvalRunner()
runner.register_evaluator("my-custom-kind", MyEvaluator())
```

Two kinds ship built in:

- **`deterministic`** — evaluates `check` (a boolean expression, e.g.
  `"patch.dry_run.ok == true"`) against the case payload using the safe
  expression evaluator in `backend.evals.expressions` (an AST whitelist, never
  `eval()`). Scores `1.0`/`0.0`. An invalid or unresolvable expression fails
  soft (score `0.0` with an `error` detail) rather than aborting the run.
- **`llm-as-judge`** — prompts the configured `LLMProvider` (the same
  protocol `backend.reasoning.service.ReasoningService` uses; offline tests
  use `StubLLMProvider`) with the rubric and expects a JSON object mapping
  each criterion name to a value within its scale. The score is the
  weighted, scale-normalized average; a missing criterion or invalid JSON
  response fails soft (that criterion, or the whole case, scores `0.0`).

### Expression grammar

`check` and `gate.fail_if` share one safe evaluator: dotted identifiers
(`a.b.c`), numeric/string literals, bare `true`/`false`/`null`, comparisons
(`==`, `!=`, `<`, `<=`, `>`, `>=`), and `and`/`or`/`not`. Identifiers must be
valid Python identifiers joined by dots — **hyphens are not supported**
(`quality.tests-pass.mean` would parse as subtraction); use underscores in
evaluator/metric ids instead (`tests_pass`), as this doc's examples do.

## The quality gate

`gate.fail_if` is evaluated against the run's computed metrics:

```
quality.<evaluator_id>.mean   # per-evaluator mean score, in [0, 1]
cost.usd_mean / cost.usd_p95
latency.p50_seconds / latency.p95_seconds
```

`EvalRunner.evaluate_gate(spec.gate, metrics)` returns `(passed, reason)`;
`passed=True` with no gate declared. CI integration (E12) is: call
`run_offline`, then fail the pipeline step when `result.gate_passed is False`.

## Persisted results

Every run produces a new `EvalResult`, stored under
`(eval_id, eval_version, run_id)` in the `eval_results` table (SQLite/Postgres,
selected per `DATABASE_URL` — ADR-001) — **never overwritten**; the store
enforces this with a `UNIQUE(eval_id, eval_version, run_id)` constraint. A
caller-supplied `runId` that collides with an already-stored result raises
`EvalResultConflictError` (mapped to `409 Conflict` at the API) rather than
silently overwriting history. Fetch history via
`EvaluationService.get_result`/`list_results`, or the API:

```
POST /v2/evals/run                                   # {"spec": {...}, "cases": [...], "runId": "..."}
                                                       # 201 on success, 409 if runId collides
GET  /v2/evals/results/{namespace}/{name}             # ?version=... optional
GET  /v2/evals/results/{namespace}/{name}/{version}/{run_id}
```

Two evaluators sharing an `id` within one spec are rejected at parse time
(`validate_eval_spec`) — `metrics.quality` and gate-expression lookups are
keyed by evaluator id, so a duplicate would otherwise silently drop one
evaluator's score.
