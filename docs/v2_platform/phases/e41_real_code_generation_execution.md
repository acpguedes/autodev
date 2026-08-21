# E41 — Real Code Generation & Agent-Directed Execution

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35: added after initial Beta completion,
before the wave is signed off).
**Status:** Not started · **Stories:** 0/5
**Depends on:** E2 (Agent Framework), E14 (Real Task Execution & Governed
Autonomy), E16-S3 (Patches API/engine)
**Enables:** the v2.0-beta gate actually meaning "the platform can turn a
goal into working, running code" — today it does not
**Canonical source:** direct manual test, 2026-08-21 (see below); confirmed
against `backend/execution/executor.py`, `backend/agents/coder/agent.py`,
`backend/agents/planner/agent.py`, `backend/agents/base.py`,
`backend/patches/engine.py`

## Objective

Close a gap found by directly running the platform end to end against a real
OpenAI key and a trivial goal ("build a simple payment API"): AutoDev's
multi-agent pipeline (planner → analyzer → architect → coder → devops →
validator → `execute-plan`) produces genuine LLM-authored *conversation*
text, but never turns that into real files on disk or agent-directed
command execution. `execute-plan`'s own module docstring says real code
generation "is future work." This epic delivers that future work.

Two compounding defects were found, not one:

1. **`execute-plan` never calls the patch engine at all.** Its task→action
   mapping (`backend/execution/executor.py`) only derives actions by
   keyword-matching known tool names (`pytest`, `ruff`, `npm`...) inside
   free-text task descriptions. `backend.patches.engine.generate_patch`/
   `apply_patch` are only reachable through the separate, human-driven
   `/v2/sessions/{id}/patches` API (`backend/api/routers/patches_review_v2.py`).
2. **Even the free-text task descriptions agents are supposed to produce are
   not real.** `PlannerAgent.build_metadata()` (`backend/agents/planner/agent.py:48-54`)
   discards the real LLM response and always returns the hardcoded
   `fallback_result()` steps. `CoderAgent` does not override `build_metadata()`
   at all, so it inherits the base default (`backend/agents/base.py:108-114`),
   which also always returns `fallback.metadata` — regardless of whether the
   real LLM call succeeded. Verified live: the coder's `content` field held
   genuine, on-topic GPT text about a payment API; the `coding_tasks`
   metadata that `execute-plan` actually reads was the same 4 generic
   hardcoded tasks every time.

## Key result

Given a small, concrete goal and a real LLM provider configured, running
`autodev plan` → `autodev run message` → `autodev run execute-plan` writes
real, working files to the configured project root and, where the plan
calls for it, runs real commands (install deps, run tests) inside the
existing E32 isolated execution environment — with no manual glue script,
and with a self-check step that catches an obviously broken first attempt.

## Stories

### E41-S1 — Structured agent output actually reaches metadata — **Not started**

Fix the discovered `build_metadata()` gap across `LangChainAgent` and its
subclasses so a successful real LLM call's `generated_text` is what ends up
validated against each agent's `metadata_model()` — not silently replaced by
`fallback_result()`'s canned data. Prefer LangChain's structured-output
binding (`model.with_structured_output(metadata_model())`) over free-text
prompting plus manual parsing, since manual parsing is what made the
original fallback substitution easy to ship unnoticed.

Subtasks:
- `E41-S1-T1`: audit every `LangChainAgent` subclass
  (`backend/agents/*/agent.py`) for the same class of bug — any
  `build_metadata()` override (or lack of one) that ignores `generated_text`
  on a successful call.
- `E41-S1-T2`: switch agents whose `metadata_model()` is defined to
  structured-output binding where the provider supports it (OpenAI does);
  fall back to parsing `generated_text` only for providers that don't.
- `E41-S1-T3`: regression test proving a successful real (or realistic
  mocked) LLM call's content is reflected in stored `artifacts[agent.name]`
  metadata — not the fallback constant — for every affected agent.

| Criterion | Detail |
| --- | --- |
| Functional | For each affected agent, a successful LLM call's structured output is what is persisted to `session_record.artifacts`; only a failed/unconfigured call uses `fallback_result()` |
| Non-functional | No change to agents whose `metadata_model()` is `None` (nothing to structure) |
| DoR (specific) | E2 agent framework available; audit list of affected agents complete |
| DoD (specific) | Contract test per affected agent asserting real-vs-fallback metadata divergence is observable |
| Dependencies | E2 |

### E41-S2 — Real code-generation contract for the Coder agent — **Not started**

`CoderAgent.build_prompt()` today only asks for "concrete coding tasks
grouped by component" (free text). Give it (or a new, dedicated agent role)
a contract that returns actual file paths and full file content — the same
shape I hand-authored manually in the smoke-test script (`{path, content}`
pairs) — validated through a new `CoderOutput`-family Pydantic model.

Subtasks:
- `E41-S2-T1`: extend/replace `CoderOutput` (`backend/agents/contracts.py`)
  with a `files: list[{path, content}]` (or diff-shaped) field alongside the
  existing task-list field — additive, does not break existing consumers of
  `coding_tasks`.
- `E41-S2-T2`: update `CoderAgent`'s prompt to request real, runnable file
  content for the declared task scope, not just descriptions.
- `E41-S2-T3`: bound generation scope for Beta (e.g. cap file count/size per
  task) so a single coder call can't attempt an unbounded rewrite.

| Criterion | Detail |
| --- | --- |
| Functional | Given a small goal, `CoderAgent`'s real-provider output includes at least one `{path, content}` file entry relevant to the goal |
| Non-functional | Stub-provider path unaffected (still returns `fallback_result()`) |
| DoR (specific) | E41-S1 landed (structured output must actually reach metadata first) |
| DoD (specific) | Contract test asserting file entries parse and validate against the new model |
| Dependencies | E41-S1 |

### E41-S3 — Patch-engine wiring in the executor — **Not started**

Give `backend/execution/executor.py` a real code-generation action path: a
new `ExecutionActionType` (e.g. `apply_patch`) derived from tasks that now
carry real file content (E41-S2), dispatched through the same
`backend.patches.engine.generate_patch`/`apply_patch` functions the Patches
API already uses — reusing that exact, already-tested mechanism rather than
inventing a second one. Gated by the same approval-mode/policy machinery
(E14) and `AUTODEV_ENABLE_PATCH_APPLY`/policy-approval semantics that govern
every other execution action.

Subtasks:
- `E41-S3-T1`: `ExecutionActionType.APPLY_PATCH` (or equivalent) in
  `backend/execution/contracts.py`; executor derives it from coder tasks
  carrying `files` entries.
- `E41-S3-T2`: dispatch calls `generate_patch`/`apply_patch` with `root`
  resolved from the run's environment/workspace (E32), not a caller-supplied
  path — closing exactly the class of misconfiguration risk found manually
  during the smoke test (a stale `project_root` writing into the wrong
  directory).
- `E41-S3-T3`: patch-apply actions go through the same approval-mode pause
  as any other action in `approval`/`hybrid` execution mode (E14-S3) — a
  human can review a real file write before it happens, exactly like the
  existing Patches API review flow.

| Criterion | Detail |
| --- | --- |
| Functional | `execute-plan` on a goal with coder-provided file content writes those files to the run's resolved workspace; in `approval`/`hybrid` mode the write pauses for approval first |
| Non-functional | No new path-traversal surface beyond what `apply_patch`'s existing guard already covers |
| DoR (specific) | E41-S2 landed; E14 execution-mode contract available |
| DoD (specific) | End-to-end test: goal → real files on disk in a scratch workspace, asserted by content, not just by call count |
| Dependencies | E41-S2, E14-S3, E32 (workspace resolution) |

### E41-S4 — Agent-directed command execution — **Not started**

Command execution already exists (`_extract_validation_command` +
`ActionRunner` + the E32 isolated environment) but fires only when a known
tool name coincidentally appears as a substring of free-text task
description — not because a DevOps/Validator agent explicitly decided what
to run. Once E41-S1 makes structured output real, give DevOps/Validator
agents a structured `commands: list[str]` contract and have the executor
prefer that over keyword sniffing.

Subtasks:
- `E41-S4-T1`: extend DevOps/Validator `metadata_model()`s with a structured
  `commands` field (e.g. `["pip install -e .", "pytest tests/"]`).
- `E41-S4-T2`: executor prefers structured `commands` when present; keyword
  heuristic remains as a fallback only for the stub/unconfigured-provider
  path, so local/no-key dev workflows keep working unchanged.
- `E41-S4-T3`: commands still run inside the existing E32 isolated
  environment and existing approval-mode gates — no new execution surface,
  only a better-informed source for what gets executed.

| Criterion | Detail |
| --- | --- |
| Functional | With a real provider, `execute-plan` runs agent-declared commands (not keyword-matched ones) inside the E32 environment |
| Non-functional | Stub-provider behavior unchanged |
| DoR (specific) | E41-S1 landed |
| DoD (specific) | Test asserting a command absent from any task's free text but present in structured `commands` still executes |
| Dependencies | E41-S1, E32 |

### E41-S5 — Self-verification loop (generate → test → repair) — **Not started**

Once real files can be written and real commands run (E41-S2/S3/S4), close
the loop: after applying generated files, run the goal's own generated
tests; on failure, feed the failure output back to the coder agent for one
bounded retry before marking the task failed. Without this, "the platform
generated code" and "the platform generated code that works" remain two
different claims.

Subtasks:
- `E41-S5-T1`: after a patch-apply action, if the same or a related task
  declares a test command (E41-S4), run it and record pass/fail as part of
  the task's execution result.
- `E41-S5-T2`: on failure, one bounded retry — feed the captured
  stdout/stderr back into a follow-up coder call scoped to the same files
  only; no unbounded retry loop.
- `E41-S5-T3`: surface the outcome (first-try pass, repaired-then-pass, or
  failed-after-retry) in the run's evidence/audit trail (E11), so the Beta
  gate can assert on it mechanically rather than by claim.

| Criterion | Detail |
| --- | --- |
| Functional | A deliberately-broken first LLM attempt (mocked in tests) is caught by the test run and repaired within one retry, or explicitly reported as failed — never silently reported as complete |
| Non-functional | Retry is bounded (exactly one) and does not change behavior when no test command is declared |
| DoR (specific) | E41-S2, E41-S3, E41-S4 landed |
| DoD (specific) | Test proving both the repair-succeeds and repair-fails-after-one-retry paths report correctly |
| Dependencies | E41-S2, E41-S3, E41-S4, E12 (eval/quality patterns) |

## Contracts & decisions

- No new extension point. E41 wires already-existing, already-tested
  mechanisms (`backend.patches.engine`, the E32 execution environment, E14's
  approval-mode gates) together with a corrected agent-output contract — it
  does not introduce a second code-writing path.
- Additive only: `CoderOutput`'s new `files` field and DevOps/Validator's new
  `commands` field must not break existing consumers of `coding_tasks`/
  free-text descriptions; the stub-provider path is unaffected by design
  (E41-S2/S4 DoD).

## DoR / DoD

- **DoR:** E41-S1 audit complete (exact list of affected agents); E14/E32
  contracts reviewed as the mechanisms this epic reuses rather than
  reinvents.
- **DoD:** all story DoDs met; a goal-to-working-code run is reproducible
  end to end with a real provider and asserted by a test, not a manual
  transcript; `docs/v2_platform/progress.md` and the v2.0-beta gate (§18.9)
  updated to reference this epic's evidence; no push/PR without explicit
  authorization.
