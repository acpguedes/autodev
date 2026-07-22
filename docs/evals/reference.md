# Reference eval, on-demand trigger, and CI gate (E12-S3)

The Evaluation Service (E5) ships the typed contract, spec parser, runner,
persistence, and closed feedback loop (`docs/evals/spec.md`). What it
deliberately does **not** ship is a concrete eval you can point at and run —
resolving `dataset.ref` into `EvalCase` objects is explicitly out of that
service's scope (see `spec.md`'s "Dataset-loading scope boundary"), and
nothing wires an eval into CI as a quality gate. This story closes that gap
with three additive pieces:

1. a small, versioned, deterministic **reference eval** (`evals/reference/agent_smoke/`);
2. a **dataset loader** (`backend/evals/dataset_loader.py`) and an
   **`autodev eval run`** CLI command (`backend/cli_plugins/evals.py`) that
   resolve and run it offline, on demand;
3. a **CI workflow** (`.github/workflows/ci-evals.yml`) that runs it on every
   push/PR and fails the job if its gate fails.

None of this changes the Evaluation Service itself (`backend/evals/contract.py`,
`spec.py`, `runner.py`, `service.py`, `expressions.py` are untouched) — it is
purely a caller built on top of the existing public API.

## The reference eval

```
evals/reference/agent_smoke/
├── eval.yaml     # versioned eval.yaml spec — id: autodev/agent-smoke, version: 1.0.0
└── dataset.yaml  # 3 fixed, deterministic cases
```

`eval.yaml` targets `autodev/agent-coder`, declares `mode: offline`, two
`deterministic` evaluators (`patch_applies`, `tests_pass`), and a `gate.fail_if`
tuned to **pass** against `dataset.yaml`'s three cases:

```yaml
gate:
  fail_if: >-
    quality.tests_pass.mean < 1.0 or
    quality.patch_applies.mean < 1.0 or
    cost.usd_p95 > 0.5 or
    latency.p95_seconds > 30
```

`dataset.yaml`'s three cases (`smoke-off-by-one`, `smoke-null-check`,
`smoke-typo-rename`) each satisfy both evaluator checks
(`patch.dry_run.ok == true`, `sandbox.tests.exit_code == 0`) and stay well
under the cost (`$0.5` p95) and latency (`30s` p95) budgets — a red run means
either the fixture data drifted or the eval/runner/gate machinery itself
regressed, not a real agent failure (no live agent or LLM call is made; the
run is fully offline and deterministic, matching every other offline eval
test in this codebase's use of `StubLLMProvider`-style fixtures — the
`deterministic` evaluator kind used here does not call an LLM provider at
all).

`dataset.ref: dataset.yaml` in the spec is resolved **relative to the spec
file's own directory** by the loader described below — this is the reference
eval's dataset convention, not an Evaluation Service behavior.

## The dataset loader

`backend/evals/dataset_loader.py` is a small, additive module (it does not
modify `backend/evals/contract.py`/`service.py`/`runner.py`) with two
functions:

```python
from backend.evals.dataset_loader import load_eval_cases, resolve_dataset_path

dataset_path = resolve_dataset_path(spec_path, spec.dataset.ref)  # relative-to-spec resolution
cases = load_eval_cases(dataset_path)                             # -> list[EvalCase]
```

`load_eval_cases` expects a YAML (or JSON, which is a YAML subset) file
shaped like:

```yaml
cases:
  - case_id: some-case
    payload:
      key: value
```

and raises `EvalDatasetError` for a missing file, a non-mapping document, a
missing/empty `case_id`, a non-object `payload`, or an empty `cases` list.

## The `autodev eval run` CLI trigger

```bash
python -m backend.cli eval run evals/reference/agent_smoke/eval.yaml
# or, with an explicit dataset override / run id:
python -m backend.cli eval run evals/reference/agent_smoke/eval.yaml \
  --dataset path/to/other-dataset.yaml \
  --run-id my-run-id
```

The command: loads and validates the spec (`load_eval_spec`), rejects
anything other than `mode: offline`, resolves and loads its dataset (via the
loader above, or `--dataset` to override), runs it through
`EvaluationService(get_store()).run_offline(...)` — which **persists** the
resulting `EvalResult` through the same durable store (`SQLite`/`Postgres`,
selected by `DATABASE_URL`, per ADR-001) every other Evaluation Service caller
uses — prints the result as JSON, and exits:

| Exit code | Meaning |
|-----------|---------|
| `0`       | Run succeeded and the gate passed |
| `1`       | Run succeeded but the gate failed |
| `2`       | Spec/dataset failed to load, `mode != "offline"`, or the run itself raised an `EvalError` (e.g. a `run_id` collision) |

This is what makes it usable both as a local on-demand trigger and as a CI
gate — a non-zero exit fails the calling shell/CI job.

## The `make eval-reference` target

```bash
make eval-reference
```

is a thin wrapper around the CLI command above, pointed at the reference
eval's path — the single local entry point referenced by CI (see below) and
by this story's verification steps.

## CI gate: `.github/workflows/ci-evals.yml`

Runs on every push to `main` and every pull request: checks out the repo,
sets up Python 3.11, installs `backend/requirements.txt`, then runs

```bash
python -m backend.cli eval run evals/reference/agent_smoke/eval.yaml
```

with `pipefail` set so a non-zero CLI exit code (gate failure or run error)
fails the job — the eval result JSON is also uploaded as a build artifact
(`reference-eval-result`) for inspection regardless of outcome.

## Verifying the closed loop end-to-end

`backend/tests/integration/test_reference_eval_feedback_loop.py` runs the
reference eval through the exact same `load_eval_spec` /
`load_eval_cases` / `EvaluationService.run_offline` path as the CLI, then
`publish_snapshot` → `RoutingFeedbackService.decide_promotion` →
`Selector.select(...)`, proving that promoting the resulting snapshot changes
a subsequent routing decision — the same closed-loop shape as
`backend/tests/integration/test_routing_feedback_e2e.py` (E5-S4), but driven
by a real eval run instead of a hand-built `EvalResult` fixture.
