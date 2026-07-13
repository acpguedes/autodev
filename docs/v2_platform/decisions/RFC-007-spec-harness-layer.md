# RFC-007 — Spec & Harness Layer (`spec.yaml`, `harness.yaml`, `/v2/specs`, `/v2/harnesses`)

- **Status:** Draft
- **Epic:** E20–E25 (wave "v2.1 — Spec & Harness")
- **Date:** 2026-07-12
- **Related:** reference §22 (architecture narrative) and §18.7.12–§18.7.17
  (roadmap entries); phase docs `phases/e20_spec_core.md` …
  `phases/e25_extension_studio.md`; builds on RFC-001 (extension catalog),
  RFC-002 (`flow.yaml`), RFC-005 (`eval.yaml`), and the E14 execution
  contracts. Per-epic ADRs are still required before each epic's first story
  (agent_guide.md §5); this RFC is the layer-level proposal they refine.

## Summary

Proposes a new platform layer that makes **specifications** and **agent
harnesses** first-class, governed artifacts:

- `spec.yaml` + a project **constitution** — versioned requirement documents
  (EARS grammar, acceptance scenarios, design, task refs) in a tenant-scoped
  Spec Registry with a delta/change-proposal model for brownfield edits
  (**E20**);
- a **Spec Compiler** that turns approved requirements into an approvable
  design + task dependency graph (waves), compiled to ordinary `flow.yaml`
  runs, with a persisted requirement↔task↔run↔patch↔test↔eval traceability
  graph (**E21**);
- **mechanical verification** — acceptance criteria compiled to runnable
  sandbox tests, requirement-targeted evals, Intent-vs-Evidence-graph drift
  detection as a blocking `validation_gate`, and same-change spec+code
  coupling with HARD/SOFT/AUTO tiers (**E22**);
- `harness.yaml` — the harness as a named unit binding spec + flow + loop
  policy + verification gates + budgets, with typed result states, durable
  loop state, parallel isolation, and a candidate-race pattern (**E23**);
- two operator surfaces: the **Spec Studio** (AI-assisted authoring/review UI,
  **E24**) and the **Extension Studio** (AI-assisted development of the
  platform's own agents/skills/plugins, gated on contract tests and sandboxed
  evidence, **E25**).

The layer is **additive**: the Flow Engine, Evaluation Service, Plugin Host,
and E14 execution contracts are consumed unchanged.

## Motivation

The v2 platform executes work well (flows, budgets, checkpoints, approval
gates, patches, sandbox validation) but has no first-class representation of
**intent**: no requirement artifacts, no spec registry, no compiler from
requirements to tasks, no requirement-level traceability, and no named outer
loop that iterates execution against acceptance criteria until they
mechanically pass. Competing products (Cursor, Claude Code, Codex,
Antigravity) all ship strong harnesses; spec-driven tools (Spec Kit, Kiro,
OpenSpec, Tessl) all ship spec authoring — none integrates both over durable
state with API-first governance. That integration is exactly the platform's
stated priority profile (API-first, durable state, patch-based workflows,
validation execution) and is where this proposal positions it.

### Prior art and what it teaches

Spec-driven development (SDD):

- **GitHub Spec Kit** (`specify` CLI) — constitution + gated phases
  (specify → clarify → plan → tasks → implement → analyze); agent-agnostic;
  weak at brownfield, gates are documentary.
  <https://github.com/github/spec-kit>,
  <https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/>
- **Amazon Kiro** — per-feature `requirements.md` (**EARS** notation:
  `WHEN <condition> THE SYSTEM SHALL <behavior>`), `design.md`, `tasks.md`;
  steering files + agent hooks; task dependency graph executed in waves.
  <https://kiro.dev/docs/specs/>
- **OpenSpec** — brownfield-first: requirement-scoped **ADDED/MODIFIED/
  REMOVED deltas**, `propose → apply → sync → archive` lifecycle; validation
  deliberately non-blocking. <https://github.com/Fission-AI/OpenSpec>
- **Tessl** — spec-as-source (code as build artifact, generation stamps,
  tests generated from spec examples) + a registry of specs for external
  libraries; framework still not GA — a signal to *not* bet the platform on
  pure spec-as-source. <https://tessl.io/>, <https://docs.tessl.io/>
- **BMAD-METHOD** — role-specialized agent pipeline over sharded PRD/story
  files (context-management by document sharding).
  <https://github.com/bmad-code-org/BMAD-METHOD>
- **Spec Growth Engine** (arXiv 2606.27045) — spec-anchored, code-coupled,
  drift-enforced: Intent Graph (from specs) vs Evidence Graph (from static
  analysis), divergence blocks the merge; same-commit spec+code coupling;
  scoped context ("the Spine"); HARD/SOFT/AUTO governance tiers.
  <https://arxiv.org/abs/2606.27045>
- Failure modes to design against (Nearform, Thoughtworks): SDD is execution,
  not discovery (prototype first); don't apply full ceremony to trivial
  changes; structure validation ≠ behavioral verification; silent spec→code
  drift is the default outcome unless enforcement is mechanical.
  <https://nearform.com/insights/lessons-from-real-world-failures-using-spec-driven-development>

Harness & loop engineering:

- **Anthropic** — workflow patterns (chaining, routing, parallelization,
  orchestrator-workers, evaluator-optimizer); agent-loop controls
  (turns/budgets, resume/fork); long-running pattern: feature-list JSON where
  every item starts *failing*, progress journal, session-init checklist,
  external verification before "done"; skills/hooks/subagents/MCP as the
  extensibility stack.
  <https://www.anthropic.com/engineering/building-effective-agents>,
  <https://www.anthropic.com/engineering/claude-code-best-practices>
- **OpenAI Codex** — "harness engineering": one harness across surfaces;
  hard isolation of harness (credentials/orchestration) from sandbox
  (execution); OS-native confinement (Landlock/Seatbelt); tiered permissions;
  event triggers for background agents.
- **Cursor** — parallel agents with per-agent working set/model/approval
  policy; the **race** pattern (same task → N models → pick best).
- **Google Antigravity** — **verification artifacts** (plans, screenshots,
  recordings) as the human trust surface; agent-manager for many async
  agents; browser-in-the-loop evidence.
- **Ralph loop** (G. Huntley) — fresh context per iteration, all state
  re-hydrated from disk, an *external validator* gates success.
  <https://ghuntley.com/loop/>
- **OSS references** — OpenHands (controller/event-stream, Docker per task)
  <https://github.com/All-Hands-AI/OpenHands>; SWE-agent (Agent-Computer
  Interface: interface design moves resolution at fixed model capability)
  <https://github.com/SWE-agent/SWE-agent>; Aider architect/editor dual-model
  <https://aider.chat/2024/09/26/architect.html>; LangGraph durable
  checkpointing <https://github.com/langchain-ai/langgraph>.

### Posture decision

Among the three SDD postures — *spec-first* (spec launches work, then goes
stale), *spec-anchored* (spec persists and evolves with code), *spec-as-source*
(code is a generated artifact) — this layer adopts **spec-anchored,
code-coupled, drift-enforced**: code remains the executable source of truth,
the spec is a verified contract kept authoritative by (a) executable
acceptance criteria, (b) a blocking drift gate, and (c) same-change spec+code
coupling. Spec-first is rejected because it reproduces the drift problem;
spec-as-source is rejected as an unproven ecosystem bet (Tessl not GA).

## Contract surface

New artifacts (all following the established manifest shape — `schemaVersion`,
`id` `namespace/name`, SemVer `version`, `hostApi`, published JSON schema, SDK
export, mandatory contract test):

- **`constitution`** — project-wide steering principles; exported to
  `AGENTS.md`/`CLAUDE.md` for external-agent interop.
- **`spec.yaml`** — `requirements[]` (EARS clauses, stable IDs `R-<n>`),
  `design` (public contract vs. internal design), `acceptance[]`
  (Given/When/Then bound to requirement IDs), `tasks[]` refs.
- **change proposal** — requirement-scoped ADDED/MODIFIED/REMOVED deltas with
  `propose → apply → sync → archive` lifecycle.
- **task graph** — tasks with `implements: [R-…]`, `dependsOn`, computed
  waves; compiled to ordinary `flow.yaml`.
- **`harness.yaml`** — `{spec, flow, loop, gates[], budgets, context}` with
  typed result states
  `success | max_iterations | max_budget | stalled | needs_human | error`.

New extension-point kinds (RFC-001 catalog, additive): `loop_policy`
(evaluator-optimizer, fresh-context, circuit-breaker, heartbeat reference
implementations) and the spec-aware `context_provider` profile ("Spine"
bundles). The drift gate ships as a `validation_gate` plugin (existing kind);
the acceptance compiler ships as a `skill` (existing kind).

New `/v2` surfaces (additive, §14.1 conventions): `/v2/specs` (+ changes,
trace, constitution) and `/v2/harnesses` (+ runs, iteration detail, SSE via
the E9-S2 transport). New event families (append-only): `spec.*`, `harness.*`.

Extended contracts (additive MINOR): `eval.yaml` gains
`target: {type: requirement, ref: <spec>#R-<n>}` (RFC-005 amendment recorded
in the E22 ADR).

## Contract rules

1. **Additive only** — no existing manifest, API, or event contract changes
   shape; the Flow Engine, Evaluation Service, Plugin Host, Agent Runtime,
   and E14 execution contracts are consumed, not modified.
2. **External validation gates "done"** — a harness run can reach `success`
   only through gate verdicts (tests/evals/drift checks executed by the
   platform), never through model self-assessment.
3. **Published versions are immutable** (specs, harnesses, task graphs);
   runs freeze resolved versions for replay, matching §19 semantics.
4. **API-first (§2.13)** — every operation of the layer is a `/v2` operation;
   the Studios and any CLI are pure clients.
5. **Tiered enforcement** — drift/coupling gates run at HARD/SOFT/AUTO tiers
   by blast radius so trivial changes are not taxed with full ceremony (the
   documented anti-pattern), but bypass is a recorded waiver, never silence.
6. **Determinism boundary** — spec compilation and acceptance-test generation
   are deterministic for frozen inputs (ADR-005 discipline extended to the
   new compilers).

## Rejected alternatives

- **Spec-as-source / code as build artifact** — rejected (unproven at
  platform scale; conflicts with the patch-based workflow priority).
- **Specs as markdown-only convention (Spec Kit style) without registry or
  enforcement** — rejected: reproduces the "spec-first scaffolding that
  drifts" failure mode; no traceability or gates possible.
- **A new loop runtime separate from the Flow Engine** — rejected: E3 already
  provides checkpointed, budgeted, resumable DAG execution; the harness owns
  only iteration policy + durable loop state (boundary to be fixed in the E23
  ADR, mirroring ADR-007/ADR-008 discipline).
- **Extending `plan_documents` (E16-S2) into a requirements store** —
  rejected: plans are execution task lists with approval state; requirements
  need SemVer versioning, deltas, and traceability edges. The compiler links
  the two instead.
- **LLM-judge-only acceptance** — rejected as the default: deterministic
  compiled tests are the primary gate; llm-judge rubrics compose via
  `eval.yaml` where determinism is impossible.

## Rollout

1. **RFC review** — this document moves Draft → Under review → Accepted per
   §19.3 before any E20 story starts.
2. **Per-epic ADRs** — E20 (spec contract & registry boundary), E21 (task &
   traceability contracts), E22 (drift model, gate tiers, eval-target
   amendment), E23 (harness vs. Flow Engine boundary, result-state
   vocabulary); E24/E25 record lightweight ADRs only if they introduce
   contract changes.
3. **Sequencing** — E20 → E21 → E22 → E23 → E24/E25 (the last two
   parallelizable); E22/E23's execution-dependent stories are gated on E14
   (S1–S4) and E12 landing first, which concentrates near-term pressure on
   finishing those v2.0 epics.
4. **Wave** — delivered as **v2.1 — Spec & Harness** (§18.9), after the
   v2.0 GA gate; E20-S1/S2 (contracts + registry) may start earlier since
   they touch no v2.0 exit criterion.

## References (research annex)

Consolidated sources from the July 2026 research pass, beyond those cited
inline above.

Harness engineering & platform teardowns:

- Anthropic — Effective harnesses for long-running agents:
  <https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents>
- Anthropic — Building a C compiler with a team of parallel Claudes:
  <https://www.anthropic.com/engineering/building-c-compiler>
- Claude Agent SDK — How the agent loop works:
  <https://code.claude.com/docs/en/agent-sdk/agent-loop>
- Claude Code — Parallel sessions with worktrees:
  <https://code.claude.com/docs/en/worktrees>
- OpenAI — Harness engineering: <https://openai.com/index/harness-engineering/>
- OpenAI — Unrolling the Codex agent loop:
  <https://openai.com/index/unrolling-the-codex-agent-loop/>
- Cursor — Introducing Cursor 2.0 and Composer:
  <https://cursor.com/blog/2-0>
- Google Antigravity: <https://antigravity.google/> and
  <https://developers.googleblog.com/build-with-google-antigravity-our-new-agentic-development-platform/>
- LangChain — The Anatomy of an Agent Harness:
  <https://www.langchain.com/blog/the-anatomy-of-an-agent-harness>

Harness taxonomy & evaluation discipline:

- Agent Harness Engineering: A Survey (OpenReview, ETCLOVG taxonomy):
  <https://openreview.net/pdf?id=eONq7FdiHa>
- Stop Comparing LLM Agents Without Disclosing the Harness (arXiv):
  <https://arxiv.org/pdf/2605.23950>
- From Question Answering to Task Completion — Agent System and Harness
  Design (arXiv): <https://arxiv.org/html/2606.20683v1>

Loop engineering:

- vercel-labs/ralph-loop-agent:
  <https://github.com/vercel-labs/ralph-loop-agent>
- Loop-engineering design patterns (2026):
  <https://datasciencedojo.com/blog/loop-engineering-design-patterns/>
- Ralph loops & ruthless context resets (LinearB/HumanLayer):
  <https://linearb.io/blog/dex-horthy-humanlayer-rpi-methodology-ralph-loop>

Worktree-isolation gotchas to design around (E23-S4):

- git config lock contention across parallel worktrees:
  <https://github.com/anthropics/claude-code/issues/34645>
- per-worktree access isolation:
  <https://github.com/anthropics/claude-code/issues/34370>

## Open questions

- EARS subset: which trigger variants (WHEN/WHILE/WHERE/IF) does v1 of the
  grammar accept, and how strict is clause linting at registration vs. review?
- Acceptance-compiler language coverage: Python/pytest first (mirroring
  E7-S1's Python-first tree-sitter scope) — what is the second target?
- Drift-gate default tier for existing (pre-spec) projects: SOFT or AUTO on
  onboarding, and what is the ramp to HARD?
- Should the constitution also feed the E5 Router/Selector (steering-aware
  agent selection), or stay context-only in v2.1?
- Library-spec registry (Tessl-style specs for external dependencies): in
  scope for a later epic or out of scope for the platform?
