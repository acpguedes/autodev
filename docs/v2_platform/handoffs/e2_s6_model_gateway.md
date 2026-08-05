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
| Task 2: gateway/adapters/fallback/limits/tracing | **Partially complete** | Main implementation is in `7090b01`; review failed. Interrupted corrective edits are checkpointed in `f1d10c6` and have not been tested or rereviewed. |
| Task 3: runtime/flow/global settings/API/acceptance telemetry | Not started | Do not start until Task 2 review is clean. |
| Task 4: public docs/Traycer matrix/examples/versioning/story closure | Not started | Do not mark E2-S6 or E2 complete before this slice. |
| Final graph, story validation, epic validation, review, merge, and PR | Not started | No story/epic merge has been performed. |

### First exact pending task

Resume **Task 2 review fix round 1** at `f1d10c6`: inspect the checkpointed native
structured-output and streamed-cost changes, run the focused Task 2 tests, fix only
failures required by the two Important findings, and obtain a clean independent
rereview. Do not start Task 3 before this gate. The remaining Minor first-token
prefetch finding must be fixed or explicitly adjudicated during that rereview.

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

### Open until verified

- Task 2 Important: `7090b01` implemented structured output by parsing plain response
  content rather than invoking LangChain/provider native structured-output mode.
  `f1d10c6` attempts to use `with_structured_output(..., include_raw=True)` and
  normalize its native result, but this is untested and not rereviewed. In particular,
  confirm whether passing `tools` and `strict` is portable across the registered
  OpenAI/Ollama LangChain implementations and fails explicitly where unsupported.
- Task 2 Important: streaming in `7090b01` did not carry, trace, or enforce estimated
  cost. `f1d10c6` adds `StreamChunk.cost`, propagation, limit checks, and tests, but
  this is untested and not rereviewed. Verify budget/error telemetry and all contract
  consumers.
- Task 2 Minor: the LangChain stream adapter pulls one provider item ahead before
  yielding the current chunk. This can delay first-token delivery and surface a later
  iterator error before the caller receives an earlier chunk. It remains open.

The pre-WIP Task 2 report saying "No Task 2 blocker remains" is superseded by the
later independent review and must not be treated as current.

## Tests and checks actually executed

No test, formatter, linter, type checker, graph update, build, or full suite was run
after the `f1d10c6` changes. Only `git diff --check` was run on that uncommitted diff;
it exited 0 before the WIP commit.

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
