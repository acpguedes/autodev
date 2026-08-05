# E2-S6 Model Gateway Emergency Recovery Handoff

This document is the neutral, self-contained recovery point for the interrupted
E2-S6 implementation. E2-S6 is **not complete**. Do not merge the story or mark E2
Done until the open review findings, runtime integration, acceptance tests, public
documentation, and required validation are complete.

## Approved objective and scope

E2-S6 is a corrective v2 story that makes model selection executable while keeping
the existing AutoDev internal-agent abstraction intact. The approved vertical slice
must:

- let each internal AutoDev agent declare a model;
- keep a global model as fallback and accept an optional execution override;
- resolve configuration in this order: execution override, agent manifest, global
  default, then an explicit error;
- normalize messages, responses, usage, errors, tool calls, structured output,
  streaming, and execution metadata through AutoDev-owned contracts;
- provide ordered, opt-in retry/fallback with explicit capability and budget checks;
- keep the deterministic provider stub fully offline and credential-free;
- preserve schema 2.0 manifests and the existing `LLMProvider` injection contract;
- emit at least agent, provider, model, latency, token, estimated-cost, fallback, and
  error telemetry;
- document the AutoDev/Traycer comparison and the LiteLLM decision using verifiable
  evidence.

Explicit non-goals are parallel scheduling, Agent-to-Agent protocols, shared-context
ACLs, external coding-agent harnesses, a cross-provider pricing catalog, and a UI
redesign. These belong to later extension points or roadmap work.

## Checkpoint identity

- Repository checkout: `/home/acpguedes/projects/tmp/autodev`
- Repository remote: `origin = git@github.com:acpguedes/autodev.git`
- Story worktree: `/tmp/autodev-e2-s6`
- Story branch: `story/e2-s6-model-gateway`
- Story base branch: `epic/e2-agent-framework`
- Merge-base and base HEAD:
  `7708430d85154c7959be637ff87d1a354d7a81e3`
- Base subject: `fix(e12-s4): harden validation gate execution (#96)`
- Remote epic base: `origin/epic/e2-agent-framework` at the same base commit
- Intended checkpoint ref: `origin/story/e2-s6-model-gateway`

Worktrees recorded before the emergency commits:

```text
/home/acpguedes/projects/tmp/autodev  7708430 [main]
/tmp/autodev-e2-s6                    7090b01 [story/e2-s6-model-gateway]
```

There was no story upstream before the emergency push. Before the WIP commit,
`git status --short --branch` showed exactly nine modified tracked files and no
untracked files. Those files were inspected; no credentials, secrets, caches,
virtual environments, generated graph data, or temporary artifacts were staged.
`git diff --check` was clean. The interrupted implementation was preserved as:

```text
f1d10c65da6de6927e4ba72c58ea5143cd7b6836
wip(e2-s6): checkpoint model gateway
```

## Relevant commits

| Commit | Purpose | State |
| --- | --- | --- |
| `7708430d85154c7959be637ff87d1a354d7a81e3` | Story/epic base | Existing main/epic commit |
| `f7e895c190e91dd62752d72c6a97af339e3f864d` | Provider-neutral contracts, model configuration, ADR, and E2-S6 tracker opening | Reviewed; later corrected by `9536482` |
| `9536482fb3384d526c4365cd3ddea8a4769d70d4` | Complete capability/error taxonomy and recursive sensitive-key guard | Targeted tests green; rereview clean |
| `7090b010d4e74e40c98a99c85da27042f216f60b` | Registry, gateway, adapters, governed fallback/limits, tracing, and tests | Targeted tests green; subsequent review found two Important and one Minor issues |
| `f1d10c65da6de6927e4ba72c58ea5143cd7b6836` | Emergency WIP for native structured output and streamed-cost handling | **Unverified; no tests run after these edits** |

The handoff itself is intentionally committed separately with subject
`docs(e2-s6): add model gateway recovery handoff`; obtain its hash with
`git log -1 --format='%H %s'` after restoring the branch.

## Current architectural decisions

1. **AutoDev owns the contract.** Domain code imports immutable, provider-neutral
   types from `backend.llm`; OpenAI, LangChain, or other provider SDK objects must not
   cross the adapter boundary.
2. **Adapters are replaceable.** The in-tree stub is first-class. The current
   LangChain path is a compatibility adapter for OpenAI/Ollama, not the product
   contract. New providers register behind the internal protocol.
3. **LiteLLM is deferred.** ADR-016 compares direct adapters, embedded LiteLLM,
   LiteLLM Proxy, and the existing LangChain factory. The accepted increment adds no
   production dependency. A future LiteLLM integration must be a replaceable adapter,
   never the central domain API.
4. **Configuration is additive.** Agent schema 2.1 adds top-level `model`; schema 2.0
   remains valid. Legacy string `policy.model` remains a provider-inheriting alias.
   Declaring both forms is rejected.
5. **Precedence is deterministic.** Execution override wins over agent configuration,
   which wins over global configuration. Absence of every valid source is an explicit
   error. An omitted provider may inherit the global provider, but fallback lists are
   never silently inherited from lower precedence.
6. **Fallback is governed.** Retry/fallback is opt-in, ordered, and limited to exact
   configured `fallbackOn` error codes. Capability fallback requires
   `unsupported_capability`. No silent degradation is allowed.
7. **Capabilities and errors are stable vocabulary.** Capabilities are exactly
   `text`, `streaming`, `tool_calling`, and `structured_output`. Required error codes
   are `provider_not_configured`, `unsupported_capability`, `authentication`,
   `invalid_request`, `rate_limit`, `timeout`, `unavailable`, `budget_exceeded`, and
   `provider_error`.
8. **Secrets stay outside manifests and contracts.** Configuration rejects
   credential-like keys recursively; adapter errors are redacted. Runtime secret
   injection remains at the existing settings/composition boundary.
9. **Internal and external agents remain distinct.** An AutoDev agent is defined by
   the Agent Manifest and executed by `AgentRuntime`. Codex, Claude Code, Cursor, and
   OpenCode are external coding agents with process/workspace/approval semantics; a
   future `CodingAgentHarness` must model them separately rather than disguising them
   as model providers.
10. **Rollback remains additive.** Stop selecting schema 2.1 model configuration and
    route calls through the existing E2-S4 provider/LangChain factory path. Existing
    schema 2.0 manifests require no persisted-data migration. Use normal revert/PR
    workflow if code rollback is needed; do not reset or discard the checkpoint.

The authoritative decision is
`docs/v2_platform/decisions/ADR-016-model-gateway.md`.

## Work state

| Slice | State | Notes |
| --- | --- | --- |
| Baseline validation | Complete | Full local baseline was green on exact base `7708430`; it does not validate later story commits. |
| Task 1: contract/governance/configuration | Complete | Commits `f7e895c` and `9536482`; scoped rereview clean. |
| Task 2: gateway/adapters/fallback/limits/tracing | **Fix rounds 1-5 applied; another confirmation rereview required** | `7090b01` + `f1d10c6`, corrected by `e3b2a0c`, `ccb6ae0`, `e321c11`, `6a308b3`, and `54f66d4`. Round 4 was the first delta a review found clean. Round 5 fixed the redaction regex itself, which had been bypassable for the whole story. |
| Task 3: runtime/flow/global settings/acceptance telemetry | **Complete** (`c158278`) | Gateway wired into `AgentRuntime` with per-execution override, global `LLM_MODEL` default, and telemetry aggregated into `AgentRunResult.metrics`. Flow propagation needs no change: `flows/handlers.py` already accepts an injected runtime. No API endpoint constructs a runtime, so there was nothing to propagate there. |
| Task 4: public docs/Traycer matrix/examples/versioning/story closure | **Partially complete** | Traycer evidence matrix published (`8756e88`). Public configuration/examples, versioning, and story closure remain. |
| Final graph, story validation, epic validation, review, merge, and PR | Not started | No story/epic merge has been performed. |

### Work done on branch `traycer/e2-s6-model-gateway-resume`

Traycer created this branch from the `d3e13b4` checkpoint. Ancestry with
`origin/story/e2-s6-model-gateway` was verified; no fast-forward was needed. The
branch is pushed to `origin` and has **not** been merged into the story branch.

| Commit | Content |
| --- | --- |
| `e3b2a0c` | Task 2 fix round 1: capability-honest native structured output, explicit failure when streaming is combined with a structured schema, stream prefetch replaced by a terminal chunk, cost-absence policy pinned by test. |
| `8756e88` | Traycer/AutoDev evidence matrix (`docs/v2_platform/model_gateway_agent_comparison.md`) plus ADR-016 cross-references. |
| `ccb6ae0` | Task 2 fix round 2: findings from the first independent rereview — 2 Critical, 6 Important, 5 Minor. One of these fixes did not work and one introduced a regression; both corrected in `e321c11`. |
| `e321c11` | Task 2 fix round 3: credential leak onto spans, the two bad fixes from `ccb6ae0`, and three non-discriminating tests. Its span fix was incomplete and it introduced one regression. |
| `6a308b3` | Task 2 fix round 4: credential leak through the `__cause__` chain (spans **and** logs), `GeneratorExit` on the span channel, the round-3 visibility regression, unbounded stream telemetry, and two uncovered streaming paths. |
| `77e8e06` | Formatting-only: black on the remaining story files, ASTs verified identical. |
| `54f66d4` | Task 2 fix round 5: redaction bypassed by quoted/dict-repr credentials and URL userinfo; span-vs-caller error-code divergence; taxonomy code dropped by the TypeError guard; guards for the seven unprotected redaction sites. |

`f1d10c6` turned out to pass the pre-existing focused suite unchanged; the real
defects it left were found by reading and by the independent rereview, not by a
failing test. Do not treat "the WIP suite was green" as evidence again.

### First exact pending task

Read the outcome of the Task 2 confirmation rereview of `ccb6ae0`. If it is clean,
start **Task 3**: wire the gateway into the runtime, global settings, and API, and
aggregate attempt telemetry into `AgentRunResult.metrics`. The integration seam is
`AgentRuntimeContext.call_llm` (`backend/agents/runtime.py:252`); legacy
`LLMProvider` injection at `AgentRuntime.__init__` (`:286`) must keep working
unchanged, metrics are assembled in `_result` (`:455`), and global model
configuration belongs beside `llm_provider` in `backend/config/settings.py:46`.
Prefer a per-run `telemetry_sink` over the gateway's `attempts` property when
aggregating, because `attempts` is thread-local per operation.

## Files changed from the story base and their purpose

| File | Purpose |
| --- | --- |
| `backend/agents/manifest.py` | Parse and validate optional schema 2.1 agent model configuration while retaining schema 2.0 and legacy alias behavior. |
| `backend/agents/provider.py` | Preserve the existing provider API and expose compatibility conversion to the new model-provider protocol. |
| `backend/agents/schemas/agent.schema.json` | Publish additive model configuration, capability, fallback, limit, and error vocabularies. |
| `backend/llm/__init__.py` | Export the deliberate provider-neutral public surface. |
| `backend/llm/contracts.py` | Immutable normalized messages, tools, responses, usage/cost, streaming, telemetry, capability, and error contracts; WIP adds optional streamed cost. |
| `backend/llm/errors.py` | Stable typed gateway errors and redaction helpers. |
| `backend/llm/factory.py` | Add only the timeout/max-token passthrough needed by the contained LangChain adapter. |
| `backend/llm/gateway.py` | Resolve targets and execute preflight, retry, fallback, budget, streaming, and per-attempt telemetry policy; WIP adds streamed-cost accounting/enforcement. |
| `backend/llm/gateway_state.py` | Internal prepared-target/budget state; WIP extracts shared limit checks. |
| `backend/llm/langchain_adapter.py` | Contain LangChain/OpenAI/Ollama types and normalize calls, tools, usage, metadata, errors, and streams; WIP attempts provider-native structured output and cost normalization. |
| `backend/llm/legacy_adapter.py` | Adapt the original text-only `LLMProvider` contract without changing callers. |
| `backend/llm/model_config.py` | Frozen model target/config/limit types plus strict parsing, precedence inputs, and recursive secret-name rejection. |
| `backend/llm/provider_protocol.py` | Structural internal provider and streaming protocols. |
| `backend/llm/registry.py` | Duplicate-safe provider registry and deterministic configuration resolution. |
| `backend/llm/stub_provider.py` | Deterministic, scriptable, offline provider with normalized calls/results/streams; WIP forwards streamed cost. |
| `backend/observability/tracing.py` | Prompt-free model span attributes and mutable measurements finalized into telemetry. |
| `backend/tests/contract/test_model_gateway_contract.py` | Contract immutability, vocabulary, normalization, and WIP streamed-cost coverage. |
| `backend/tests/unit/agents/test_agent_model_manifest.py` | Schema 2.1, schema 2.0 compatibility, legacy alias, conflict, and early-validation tests. |
| `backend/tests/unit/llm/test_llm_factory.py` | Compatibility coverage for factory parameter passthrough and existing behavior. |
| `backend/tests/unit/llm/test_model_adapters.py` | Stub, legacy, LangChain, redaction, tool/structured/stream normalization tests; WIP expects native structured mode and streamed cost. |
| `backend/tests/unit/llm/test_model_config.py` | Model configuration parsing, limits, fallback vocabulary, and recursive sensitive-key tests. |
| `backend/tests/unit/llm/test_model_gateway.py` | Precedence, preflight, retry/fallback, budgets, streaming, and WIP streamed-cost enforcement tests. |
| `backend/tests/unit/observability/test_model_tracing.py` | Model telemetry attributes and WIP streamed-cost span propagation. |
| `docs/v2_platform/decisions/ADR-016-model-gateway.md` | Accepted gateway/LiteLLM decision, consequences, and rollback. |
| `docs/v2_platform/decisions/README.md` | ADR-016 index entry. |
| `docs/v2_platform/phases/e2_agent_framework.md` | E2-S6 scope, dependency, non-goals, and In Progress state. |
| `docs/v2_platform/progress.md` | Reopen E2 temporarily at 5/6 and record the corrective story. |
| `docs/v2_platform/handoffs/e2_s6_model_gateway.md` | This recovery checkpoint. |

The planned Task 3 and Task 4 files have not been edited.

## Review findings

### Corrected and rereviewed

- Task 1 Critical: common/nested credential names such as `secretKey`, `accessKey`,
  `secretAccessKey`, `awsAccessKeyId`, token/password/credential variants could evade
  the initial fixed denylist. Corrected in `9536482` with generalized recursive
  detection and tests.
- Task 1 Important: the initial capability id used `tools`, and the error taxonomy was
  incomplete. Corrected in `9536482` to the exact capability/error vocabularies.
- Task 1 rereview found no remaining Critical or Important findings.

### Closed in `e3b2a0c` (fix round 1)

- Task 2 Important (native structured output): resolved. `ollama` is served by
  `ChatOpenAI` against an OpenAI-compatible base URL (`backend/llm/factory.py:183-196`)
  and `langchain_ollama` is not installed, so both registered providers share one
  `with_structured_output` signature. The adapter now forwards only arguments the
  provider declares and raises `unsupported_capability` on any gap. The unconditional
  `strict=True` was removed: it was coupled to the unrelated presence of tools and
  narrows schema acceptance under OpenAI strict mode.
- Task 2 Important (streamed cost): mechanics verified — `StreamChunk.cost`,
  propagation, span attributes, and telemetry all work. The enforcement *claim* was
  overstated; see the documented limitation below.
- Task 2 Minor (stream prefetch): fixed. Chunks are yielded on arrival and the stream
  closes with a terminal chunk carrying the final usage/cost snapshot.
- Found while fixing, not previously recorded: `stream()` silently discarded a
  requested `structured_output_schema`, violating the no-silent-degradation rule. It
  now fails explicitly.

### Closed in `ccb6ae0` (fix round 2, from the first independent rereview)

- **Critical** — importing the tracer at module scope closed an import cycle
  (`observability -> config -> llm.factory -> llm package -> gateway -> observability`),
  breaking any entrypoint whose first backend import was observability. The suite could
  not catch it because conftest imports the app first. Fixed with a call-time import
  and a subprocess guard test.
- **Critical** — telemetry recording and the success return sat inside the classifying
  `try`, so a failing telemetry sink discarded a paid-for response and issued a second
  billed provider call. Only the provider call is classified now; sink failures are
  isolated and logged.
- **Important** — a timed-out attempt raised before its usage/cost were accounted,
  letting a fallback chain exceed configured ceilings.
- **Important** — `_accepts_keyword` accepted a `**kwargs` catch-all, so `tools` could
  be forwarded and silently ignored. Arguments whose effect cannot be verified
  afterwards now require an explicit parameter.
- **Important** — the streaming span stayed current across `yield`, re-parenting caller
  work onto the model call. Streaming now uses a detached span.
- **Important** — span error codes were read verbatim from provider exceptions, leaking
  vendor codes outside the taxonomy. Codes are constrained, with a contract test
  pinning the observability copy to `ModelErrorCode`.
- **Important** — a test claimed fail-closed streaming cost enforcement using only
  single-chunk streams. Renamed to what it proves; see the limitation below.
- **Important** — attempt telemetry was shared mutable state that interleaved across
  threads. It is now thread-local.
- **Minor** — base `ModelGatewayError` had no `code`; `httpx.HTTPStatusError` carries
  its status on `.response` so 429/5xx were misclassified and governed
  `rate_limit`/`unavailable` fallback never fired; a non-streaming provider consumed a
  call from the budget without making one; an abandoned stream left no governance
  record; two unreachable raises used `invalid_request`.

### Closed in `e321c11` (fix round 3, from the confirmation rereview of `ccb6ae0`)

The confirmation rereview did not clear `ccb6ae0`. It found one claimed fix that did
not work, one regression introduced by the fix round, and a pre-existing credential
leak underneath both.

- **Critical, pre-existing since `7090b01`** — OpenTelemetry's
  `start_as_current_span` defaults to `record_exception=True`, attaching the raw
  provider exception to the span before redaction ran on the caller-facing error. A
  provider raising `api_key=sk-... rejected` gave the caller a redacted message and the
  span the live key. Automatic exception recording is disabled; spans carry a stable
  code and never a provider message.
- **High — `ccb6ae0` did not actually fix the span taxonomy.** `_span_error_code`
  checked `isinstance(code, str)` rather than membership, so vendor codes still reached
  spans, and its test drove `trace_model_call` directly, exercising only the branch that
  already worked. Sanitizing now happens where the span attribute is written.
- **High — `ccb6ae0` introduced a regression.** The abandoned-stream `finally` recorded
  `provider_error` on `GeneratorExit`, which fires on the ordinary
  `for chunk in stream: ... if chunk.done: break` idiom, so every successful stream was
  reported as a failure and got no success record. Abandoned attempts are now recorded
  without an error code.
- **Medium** — detached streaming spans set an explicit ERROR status; the streaming
  error path accumulates billed usage symmetrically with `complete()`; `recorded` is set
  before `_record`; `_preflight` keeps `provider=""`.

Three guards were passing without testing anything and are now mutation-checked (each
verified to fail when its fix is reverted): the thread-safety test blocks on a barrier
so it fails in a full-file run rather than passing on scheduling luck; the
capability-budget test uses two targets so it can observe the budget; the span-taxonomy
test runs through the gateway.

### Closed in `6a308b3` (fix round 4, from the confirmation rereview of `e321c11`)

That rereview did not clear `e321c11` either.

- **Critical, still open from round 3** — the credential leak was moved, not closed.
  Disabling `record_exception` on the model span left the raw exception on `__cause__`;
  OpenTelemetry formats exception chains and every *other* span (run steps, request
  middleware) still records exceptions by default, so the live key landed on the
  enclosing run-step span. The same chain reached `logging` via `exc_info=True` inside
  `_record`. The chain is now broken at the redaction boundary (`raise ... from None`,
  eight sites) and the sink log records only the exception type.
- **High, half-fixed in round 3** — `GeneratorExit` was still treated as a provider
  failure on the *span* channel, so the ordinary `break`-after-`done` idiom produced a
  clean attempt record and an ERROR span. The two governance channels disagreed.
- **Medium, regression introduced by round 3** — replacing the taxonomy fallback with
  `str(getattr(exc, "code", "") or "")` made codeless failures render as successful
  spans with no ERROR status.
- **Medium** — stream attempt telemetry grew without bound on the consuming thread; the
  reset now happens in the generator body.
- **Low** — `redacted_gateway_error` no longer raises `TypeError` for a subclass with a
  different constructor signature.

Two streaming paths the rereview found entirely uncovered now have tests, including the
"never switch providers after output reached the caller" invariant.

Two guards written this round did not discriminate on the first attempt — one drove the
gateway where the tracer's own fallback was needed, the other created and consumed a
stream on the same thread. Both were rewritten until they failed against the reverted
fix. **Mutation-check every new guard in this area; several have looked correct while
testing nothing.**

### Still open

- A confirmation rereview of `6a308b3` has not been run. **Three of four review rounds
  found real defects in the preceding round's fixes — twice in fixes that had been
  reported as complete. Do not treat Task 2 as clean without one.**
- **Recorded, not fixed:** `_stream_prepared` is ~164 lines with cyclomatic complexity
  ~31 and 7 levels of nesting at the `yield`; `complete` is ~134 lines at ~23. Both far
  exceed the project's threshold, and that density is why the `GeneratorExit`
  regression slipped in. Extracting per-attempt execution and the record-once
  bookkeeping into helpers is the recommended follow-up. It was deliberately not
  attempted late in the fix cycle.
- **User-visible behavior change to document in Task 4:** combining `tool_calling` with
  `structured_output` now raises `unsupported_capability` on any provider whose
  `with_structured_output` does not declare `tools` explicitly. `ChatOpenAI` declares
  it; the LangChain base shape does not. This is the intended no-silent-degradation
  trade, but it must be stated in the public docs.
- **`attempts` is unreliable for `stream()`.** A generator body runs on whichever thread
  calls `next()`, so a stream consumed on a worker thread records onto that worker's
  thread-local. Task 3 must aggregate telemetry through a per-run `telemetry_sink`.

The pre-WIP Task 2 report saying "No Task 2 blocker remains" is superseded and must not
be treated as current.

### Documented limitations of cost governance

These are intentional and pinned by test, not oversights:

- **No provider cost metadata means no cost enforcement.** Cost ceilings act on
  provider-reported or stub-computed estimates. A provider that reports no cost
  contributes zero, so `max_cost_usd` cannot fail closed on it. Token and call ceilings
  remain enforceable and are the reliable guardrail there.
- **Streaming cost enforcement is not pre-emptive.** Real providers report usage and
  cost on the terminal chunk, after content has been delivered. The gateway fails closed
  as soon as it learns the cost, but cannot withhold content it had no reason to block.
  Callers that must not over-spend should use `max_calls` or a non-streaming call.

## Tests and checks actually executed

### On branch `traycer/e2-s6-model-gateway-resume` at `ccb6ae0`

```text
LLM_PROVIDER=stub python -m pytest -q backend/tests -p no:randomly
1332 passed, 5 failed, 2 skipped in 598s

python -m ruff check backend tests      -> All checks passed!
python -m mypy backend                  -> Success: no issues found in 377 source files
python -m black --check <files this branch touched> -> clean
```

All 5 failures are pre-existing and environmental, demonstrated rather than assumed:

- `backend/tests/unit/validation/test_sandbox_runner.py` (4 tests) shell out to a bare
  `python` executable, which is not on `PATH` in this environment. The identical test
  fails the same way on the pristine base checkout at `7708430`.
- `test_agents_v2_registry.py::test_capability_search_returns_rankable_candidates_under_100ms`
  is a wall-clock assertion that failed only while two full suites ran back to back; it
  **passes in isolation** on this branch.

The focused Task 2 set (`backend/tests/unit/llm/`, `backend/tests/unit/observability/`,
model gateway + provider contract tests) is **87 passed**.

### Prior state, for context

No test, formatter, linter, type checker, graph update, build, or full suite was run
after the `f1d10c6` changes. Only `git diff --check` was run on that uncommitted diff;
it exited 0 before the WIP commit. When finally executed, that suite passed unchanged —
the defects in `f1d10c6` were latent and required reading and review to find.

The following earlier results are recorded evidence, not claims about current HEAD:

### Pre-story baseline at `7708430`

```text
source .venv/bin/activate && LLM_PROVIDER=stub make check
backend: 1259 passed, 2 skipped; coverage 92.02%
frontend: 40 files / 162 tests passed; build and compose checks green

source .venv/bin/activate && LLM_PROVIDER=stub make container-check
backend: 1259 passed, 2 skipped; coverage 95.40%
secret scan, Ruff, and mypy green
```

### Task 1 final correction at `9536482`

```text
source .venv/bin/activate && python -m pytest -q \
  backend/tests/contract/test_model_gateway_contract.py \
  backend/tests/unit/llm/test_model_config.py
29 passed in 0.03s

source .venv/bin/activate && python -m ruff check \
  backend/llm/contracts.py backend/llm/model_config.py \
  backend/tests/contract/test_model_gateway_contract.py \
  backend/tests/unit/llm/test_model_config.py
All checks passed!

source .venv/bin/activate && python -m mypy backend
Success: no issues found in 366 source files
```

The schema JSON validator also passed, and Task 1's post-fix rereview was clean.

### Task 2 before independent review at `7090b01`

```text
source .venv/bin/activate && python -m pytest -q \
  backend/tests/unit/llm/test_model_gateway.py \
  backend/tests/unit/llm/test_model_adapters.py \
  backend/tests/unit/observability/test_model_tracing.py \
  backend/tests/unit/llm/test_llm_factory.py \
  backend/tests/contract/test_provider_contract.py \
  backend/tests/contract/test_model_gateway_contract.py
30 passed in 0.21s

source .venv/bin/activate && python -m ruff check <Task 2 Python scope>
All checks passed!

source .venv/bin/activate && python -m mypy backend
Success: no issues found in 377 source files

git diff --check
clean, exit 0
```

### Tests still required

1. Re-run the exact Task 2 targeted suite above against `f1d10c6` and run Ruff/mypy
   only after reviewing the WIP.
2. Add or confirm negative tests for unavailable native structured output, parsing
   errors, cost metadata absence, cost-limit breach, tracing on breach, and contract
   compatibility.
3. Obtain a clean Task 2 independent rereview.
4. Implement Task 3 by TDD and run its agent-runtime/flow/config/API acceptance suite.
5. Implement Task 4 and run documentation/schema/example checks.
6. After all story tasks and reviews are clean, run the story-scoped acceptance set
   and `graphify update .`.
7. Only after merging the story into the epic branch, run
   `LLM_PROVIDER=stub make check` and `LLM_PROVIDER=stub make container-check` on the
   epic tree, then obtain whole-branch architecture/code review.

## Limitations, risks, and blockers

- **Current blocker:** Task 2 cannot be considered complete until the two Important
  findings are proven fixed and rereviewed. The emergency interruption occurred
  before any verification of `f1d10c6`.
- Real-provider capability behavior varies by model and adapter. Capability sets are
  registered explicitly so unsupported behavior can fail closed; they are not
  automatically discovered yet.
- There is no uniform pricing catalog. Cost enforcement can use deterministic stub or
  provider-reported estimates; real streamed calls that report no cost need an
  explicit documented policy before claiming fail-closed cost governance.
- Streaming never switches providers after output has reached the caller, preventing
  mixed or duplicate output. Retry/fallback before first output still needs the open
  prefetch behavior reviewed.
- Runtime/Flow wiring does not yet use the new gateway, so per-agent and execution
  model selection are not yet end-to-end features.
- Acceptance telemetry aggregation into `AgentRunResult.metrics` is not implemented.
- No external coding-agent integration, A2A, shared-context ACL, parallel scheduler,
  UI work, or advanced routing exists in this story.
- Git metadata for the worktree may require approved elevated access in restricted
  environments. This is an environment constraint, not a code failure.
- The worktree uses the main checkout's `.venv` through an ignored symlink. Recreate
  it if `/tmp` is lost; never commit it.

## Ephemeral and conversation-only information preserved here

The following inputs are not committed elsewhere and may disappear after a restart:

- Implementation plan: `/tmp/autodev-e2-s6-plan.md`.
- SDD briefs, reports, review findings, diff bundles, and ledger:
  `/tmp/autodev-e2-s6/.superpowers/sdd/autodev-e2-s6-plan/`. The `.superpowers`
  directory is intentionally ignored and must not be committed.
- Traycer evidence clone: `/tmp/traycer-evidence.1BL4tl/traycer`, remote
  `https://github.com/traycerai/traycer.git`, clean `main` at immutable commit
  `8f21d506f9945e409f4cd72f32c71e8810a4d236`. The clone is temporary.
- Preliminary Traycer conclusions for Task 4: code shows Traycer agents primarily as
  durable sessions around external coding harnesses (Claude Code, Codex, OpenCode,
  Cursor), which differs from AutoDev internal agents. Its A2A path is Host-local RPC,
  not evidence of the open Agent2Agent standard. Several host/runtime capabilities,
  parallel execution, durable memory, and enforcement claims are documented/product
  claims but cannot all be verified because the relevant host implementation is not
  public in the inspected repository. Classify every final matrix claim as
  code-confirmed, documentation-only, or unverifiable product claim.
- Traycer's inspected repository is MIT licensed. No Traycer code was copied; only
  concepts and architectural evidence were used. Recheck the exact file/license and
  immutable links when writing the final comparison.

## Completion criteria for E2-S6

E2-S6 is complete only when all of the following are true:

- Task 2 targeted tests, lint, typecheck, and independent review are clean;
- runtime composition uses the gateway without breaking explicit legacy-provider
  injection;
- two agents can use distinct models in one execution;
- global fallback and execution-over-agent-over-global precedence work end to end;
- invalid configuration/provider and missing capabilities fail before invocation;
- fallback happens only for configured typed errors;
- offline stub operation requires neither network nor credentials;
- normalized messages/tool calls/structured output/streaming stay vendor-neutral;
- agent/provider/model/tokens/cost/latency/errors/fallbacks are observable;
- schema 2.0 and legacy manifests remain supported or have tested, explicit migration;
- requested public configuration/examples, Traycer comparison/evidence matrix,
  prioritization, limitations, and LiteLLM decision are published;
- story-scoped checks are green and the story has a clean final review;
- the story is merged into `epic/e2-agent-framework` through the repository workflow;
- full `make check` and `make container-check` pass on the epic tree;
- the epic PR to `main` is reviewed and merged before branches are removed;
- only then are E2-S6 and E2 updated to Done 6/6.

## Safe reconstruction and resume commands

If the existing worktree is present:

```bash
cd /tmp/autodev-e2-s6
git status --short --branch
git branch -vv
git log --oneline --decorate -8
git rev-parse HEAD
git rev-parse origin/story/e2-s6-model-gateway
test -e .venv || ln -s /home/acpguedes/projects/tmp/autodev/.venv .venv
source .venv/bin/activate
```

If `/tmp/autodev-e2-s6` is gone but the local story branch still exists:

```bash
cd /home/acpguedes/projects/tmp/autodev
git fetch origin
git worktree add /tmp/autodev-e2-s6 story/e2-s6-model-gateway
cd /tmp/autodev-e2-s6
```

If both the worktree and local story branch are gone, reconstruct from the pushed
remote checkpoint:

```bash
cd /home/acpguedes/projects/tmp/autodev
git fetch origin story/e2-s6-model-gateway
git worktree add -b story/e2-s6-model-gateway \
  /tmp/autodev-e2-s6 origin/story/e2-s6-model-gateway
cd /tmp/autodev-e2-s6
```

Do not use stash, reset, clean, force-push, or merge as part of recovery. Inspect
`git status`, branch, HEAD, upstream, and this handoff before making changes.

## Resume prompt for Codex

```text
Resume AutoDev E2-S6 only from the committed recovery checkpoint on
story/e2-s6-model-gateway. First read AGENTS.md, CONTRIBUTING.md,
docs/v2_platform/agent_guide.md, docs/v2_platform/progress.md,
docs/v2_platform/phases/e2_agent_framework.md,
docs/v2_platform/decisions/ADR-016-model-gateway.md, and
docs/v2_platform/handoffs/e2_s6_model_gateway.md. Verify the current branch, HEAD,
upstream, merge-base 7708430d85154c7959be637ff87d1a354d7a81e3, and a clean status.
Do not reimplement completed Task 1 and do not start Task 3 yet. The first task is to
review and verify WIP commit f1d10c65da6de6927e4ba72c58ea5143cd7b6836,
which attempts to fix native LangChain structured output and streamed-cost
enforcement. Run the documented focused Task 2 tests, preserve strict typed/redacted
provider-neutral boundaries, correct only proven failures, and obtain an independent
rereview. The stream-prefetch Minor remains open. Continue Tasks 3 and 4 only after
Task 2 is clean. Never mark E2-S6 done or merge until every completion criterion in
the handoff is satisfied.
```

## Resume prompt for Claude Code

```text
Continue the AutoDev v2 E2-S6 story from the committed emergency checkpoint on
story/e2-s6-model-gateway; do not start a new implementation. Read AGENTS.md,
CONTRIBUTING.md, docs/v2_platform/agent_guide.md,
docs/v2_platform/handoffs/e2_s6_model_gateway.md, the E2 phase page, progress tracker,
and ADR-016 before editing. Confirm HEAD/upstream/status and merge-base
7708430d85154c7959be637ff87d1a354d7a81e3. Task 1 is complete. Task 2 failed review:
native structured output and streamed-cost enforcement have an untested interrupted
fix in f1d10c65da6de6927e4ba72c58ea5143cd7b6836, and stream prefetch remains a Minor
finding. First inspect that commit, run only the documented focused Task 2 checks,
fix/review those findings, and keep vendor SDK types inside adapters. Do not begin
runtime integration (Task 3), public closure (Task 4), merging, or status completion
until Task 2 has a clean independent rereview. Preserve legacy manifests/provider
injection, offline stub behavior, secrets policy, and the exact configuration
precedence/fallback semantics recorded in the handoff.
```
