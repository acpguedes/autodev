# RFC-008 — SOTA Concept Integration Layer (v2.2 wave, epics E26–E31)

- **Status:** Draft
- **Epic:** E26–E31 (wave "v2.2 — Concept Integration")
- **Date:** 2026-07-13
- **Related:** RFC-007 (Spec & Harness layer — this RFC extends its research
  pass and consumes its contracts), RFC-001 (extension catalog), RFC-004
  (Router/Selector), RFC-005 (`eval.yaml`), ADR-006 (budget propagation);
  reference §23 (architecture narrative) and §18.7.18–§18.7.23 (roadmap
  entries); phase docs `phases/e26_runtime_context_engineering.md` …
  `phases/e31_library_spec_registry.md`. Per-epic ADRs are still required
  before each epic's first story (agent_guide.md §5).

## Summary

Closes the July 2026 state-of-the-art evaluation of mainstream AI development
and AI creative platforms plus the 2024–2026 academic literature, and proposes
the final conceptual wave of the platform plan: six additive epics that
integrate every evaluated cutting-edge concept not already covered by E0–E25,
while keeping the platform strictly model-agnostic:

- **E26 — Agent Runtime Context Engineering**: KV-cache-aware runtime
  invariants, pluggable context condensers, tool masking, external-memory
  primitives (filesystem/State-Store notes, plan recitation,
  keep-errors-in-context);
- **E27 — Execution-Grounded Verification & Test-Time Compute**: best-of-N
  candidate generation with execution-based selection, multi-verifier and
  calibrated LLM-judge composition, cross-model second opinion ("oracle"),
  property-based acceptance oracles, oracle hardening against reward hacking;
- **E28 — Execution Environments & Self-Verification**: machine snapshots
  (provisioned environment images), tiered isolation (microVM class for
  untrusted code), browser self-verification runner, code-mode MCP (tools as
  code APIs executed in the sandbox);
- **E29 — Durable Learning & Skill Library**: verified, embedding-indexed
  skill/playbook library with incremental (delta-based) curation, a
  progressive-disclosure skill pack format, machine-generated repo knowledge;
- **E30 — FinOps & Autonomy Governance**: pre-run cost estimation,
  hierarchical budget caps and kill switches, draft-vs-final execution tiers,
  per-surface metering;
- **E31 — Library Spec Registry**: verified dependency specs
  ("spec-as-lockfile") resolving RFC-007's explicitly deferred open question.

The wave is **additive**: no existing manifest, API, or event contract changes
shape; E26–E31 consume the E2 runtime, E3 Flow Engine, E5 Selector/Evaluation,
E14 execution contracts, and the E20–E23 spec/harness layer unchanged.

## Motivation

RFC-007 gave the platform first-class **intent** (specs) and a governed outer
**loop** (harnesses). The remaining distance to the state of the art is not a
missing subsystem but a set of named techniques, each proven in production by
at least one mainstream platform or corroborated by peer-reviewed evidence,
that no single competitor integrates over durable, self-hostable,
model-agnostic state:

1. **Cost & coherence engineering** is the #1 operational pain of 2026:
   agentic tasks consume ~1000x the tokens of single-turn queries and
   enterprises are blowing AI budgets in months. The published Manus lessons
   (KV-cache hit rate as the primary production metric, append-only context,
   tool masking over removal, filesystem as memory) and Anthropic's context
   engineering guidance (compaction, note-taking, sub-agent isolation) are
   directly implementable, model-agnostic, and absent from our runtime
   contracts (→ E26, E30).
2. **Execution-grounded verification is the highest-leverage capability** in
   the 2024–2026 literature: execution feedback as the selection/reward
   signal (RLEF, RLVR), best-of-N generation with test-based selection
   (Agentless), property-based oracles (CANDOR), and hardened differential
   oracles (UTBoost — ~31% of benchmark "passes" survive only weak tests).
   Our E22 gates verify one candidate; nothing generates and races N
   candidates under multi-verifier selection (→ E27).
3. **Environment durability and self-verification** differentiate the best
   hosted agents: Devin's machine snapshots kill repeated setup cost;
   Antigravity agents drive a real browser to verify their own UI work;
   Anthropic's code-mode MCP cuts tool-call token overhead ~90%+ and keeps
   sensitive data inside the sandbox. All three fit our Docker/MinIO/MCP
   stack (→ E28).
4. **Agents that learn**: Voyager-style verified skill libraries and
   ACE-style incremental playbook curation improve agents without
   fine-tuning — a perfect match for a durable-state platform, and absent
   from E6/E7 (→ E29).
5. **Dependency hallucination** remains a top failure mode; Tessl's registry
   of verified per-library specs ("spec-as-lockfile") is the emerging answer
   and was explicitly deferred by RFC-007 (→ E31).

### Platform evaluation (July 2026 research pass)

AI development platforms — distinctive concepts, and what transfers:

- **Claude Code / Agent SDK (Anthropic)** — deepest composable harness:
  subagents with isolated contexts + grader-scored revision loops (Dynamic
  Workflows / Performance Outcomes), ~25 lifecycle hooks, progressive-
  disclosure skills, checkpoints/rewind, five-stage compaction, code
  execution with MCP. Weakness: extreme token consumption; checkpoints skip
  shell side effects. Concepts fully portable; production tuned to one
  vendor. → E26 (compaction), E28 (code-mode MCP), E29 (skill packs).
- **Cursor** — hybrid retrieval fusion (dense embeddings + tree-sitter
  symbol graph + LSP call graph), background agents on branches, parallel
  Agents Window, race pattern. Weakness: indexing/infra vendor-locked.
  → validates E7; race generalized in E27.
- **OpenAI Codex** — parallel cloud tasks in per-task sandboxes, AGENTS.md
  as a cross-tool standard (silent 32 KiB truncation is a design caution),
  harness/sandbox hard isolation, OS-native confinement. → validates
  E14/E23; AGENTS.md export already in E20.
- **Devin (Cognition)** — machine snapshots (resume a fully provisioned
  machine), playbooks, curated + auto-scanned repo Knowledge, auto-generated
  repo wiki, multi-Devin orchestration with isolated VMs. Weakness: fully
  hosted/proprietary. → E28-S1 (snapshots), E29 (playbooks/knowledge/wiki).
- **Manus** — the public context-engineering playbook: KV-cache hit rate as
  the north-star metric, append-only immutable context, deterministic
  serialization, logit masking over tool removal, filesystem as reversible
  external memory, todo recitation, keep errors in context. 100%
  model-agnostic. → E26 wholesale.
- **GitHub Copilot coding agent** — issue→PR loop in ephemeral CI
  environments, `copilot-setup-steps.yml` pre-provisioning, human approval
  before CI runs. GitHub-locked workflow. → validates E14 approval modes;
  pre-provisioning informs E28-S1.
- **Google Antigravity / Jules** — verification **artifacts** (plans,
  screenshots, browser recordings) as the human trust surface with inline
  comment-without-stopping; agents verify UI work in a real browser;
  planner/executor split + critic pass before PR; heavy async parallelism.
  Gemini-locked. → E22-S5 already adopts evidence bundles; browser
  self-verification → E28-S3; critic pass → E27-S2/S3.
- **Windsurf (Cascade)** — plan-preview flows with per-step approval and
  staged diffs; automatic persistent Memories from user corrections.
  → validates E16; auto-memory informs E29-S2.
- **OpenHands / Aider / Cline** (OSS reference tier) — event-stream
  architecture with pluggable **condensers** (threshold-triggered history
  compression); tree-sitter repo map; architect/editor dual-model;
  Plan/Act with per-step approval; BYOK. Closest architectural cousins;
  condensers → E26-S2, dual-model → E27-S3.
- **Factory / Amp / Warp / Replit-class** — coordinator + specialized
  droids with explicit role boundaries; **the Oracle** (a deliberately
  *different* frontier model as second opinion); open-sourced agentic
  development environment; autonomous app-gen loops whose failure mode is
  checkpoint-billing runaways. → E27-S3 (cross-model oracle — only a
  model-agnostic plane can own it), E30-S2 (checkpoint ceilings).
- **Spec Kit / Kiro / Tessl** — covered by RFC-007; the remaining transfer
  is Tessl's **Spec Registry** (10k+ verified specs for OSS libraries
  against API hallucination) → E31.

AI creative/media platforms — evaluated for transferable platform concepts
(they solved managed long-running generation 1–2 years before dev tooling):

- **ElevenLabs** — dedicated low-latency orchestration engine; visual
  workflows mixing deterministic and generative nodes; BYO-LLM behind an
  open API contract; enterprise trust surface productized. → affirms E3/E10
  and the model-agnostic posture.
- **HeyGen** — per-operation price legibility *before* running; tiered
  quality = tiered cost; documented concurrency caps as contract; one
  engine, three integration surfaces (API/MCP/skills) with separate billing
  pools. → E30-S1/S3/S4.
- **Runway / Pika / Kling** — iteration velocity as the headline metric
  (cheap batch-of-N previews, pick, refine); keyframe-bounded generation
  (pin endpoints, model fills the middle ≈ spec-anchored codegen);
  storyboard decomposition with per-shot regeneration; many models behind
  one subscription surface. → E27-S1 (batch-of-N), affirms E20/E21.
- **Google Flow / Veo** — the product is the harness around a raw model;
  extend-not-regenerate continuity editing; credit budgeting per generation
  scaled by model+settings (coarse credits frustrate power users — meter
  finer). → affirms patch-based workflows; E30-S1.
- **Suno / Udio** — simple-default vs custom escape hatch; decomposable
  outputs (stems) that are partially editable/regenerable; batch-then-refine
  draft→final pipelines; licensing/provenance retrofits broke core features
  (cautionary: bake provenance in early). → E30-S3; provenance guidance
  for E13/E31-S4.
- **Midjourney** — non-destructive composable scoped edits (vary-region,
  pan, zoom) as an iteration vocabulary; community remix library with
  privacy as a paid tier (default-public caused IP harm — dev platform
  must default private). → affirms patch vocabulary; sharing guidance.

### Evidence base (academic, 2024–2026, condensed)

- **Scaffold simplicity wins on cost-adjusted quality**: SWE-agent's
  agent-computer interface, AutoCodeRover's cheap structural search, and
  Agentless's fixed localize→generate-N→select pipeline beat elaborate
  autonomy on many tasks; scaffolding adds 5–15 points over raw models on
  agentic benchmarks — the harness is where a model-agnostic platform
  competes.
- **Benchmark skepticism is warranted**: OpenAI retired SWE-bench Verified
  after attributing 59.4% of observed failures to test flaws; memorization
  studies show file-path recall up to 76%; UTBoost found ~31% inadequate
  oracles; "building to the test" (reward hacking) is systemic. Internal
  evaluation must be decontaminated, held-out, and resource-aware (SWE-
  rebench, SWE-Effi) (→ E27-S5, shapes E12).
- **Execution-grounded rewards are the durable signal** (RLEF, RLVR/GRPO,
  dense partial-pass rewards); LLM-as-judge is noisy run-to-run and must be
  multi-sampled and calibrated, and used only for non-executable dimensions
  (→ E27-S2, extends RFC-005 posture).
- **Multi-agent restraint**: the MAST failure taxonomy attributes ~56% of
  multi-agent failures to system design and verification gaps, not model
  capability; gains over strong single-agent baselines are often minimal.
  Default topology: lean orchestrator + few verified workers with explicit
  completion contracts (guidance, not an epic).
- **Context rot is measurable** (accuracy drops as context grows even with
  all relevant facts present) — validating condensers, external memory, and
  recitation as runtime primitives (→ E26).
- **Memory without fine-tuning works**: Reflexion, Voyager skill libraries,
  and ACE's generator/reflector/curator delta curation improve task
  performance with no weight updates (→ E29).
- **Repo intelligence consensus**: tree-sitter → knowledge graph → hybrid
  (structural + embedding + lexical) retrieval (RANGER, LocAgent) —
  validates E7 and the in-repo graphify graph (→ E29-S4 alignment).
- **Agentic security**: 2026 prompt-injection taxonomies target exactly the
  MCP/skills/tools surface we expose; least-privilege capability grants and
  MAC-style mediation (Progent, SAGA) extend our default-deny broker;
  sandboxed agents show no measured capability loss (→ E28-S2, E11 scope).

## Concept disposition catalog

Every evaluated concept, dispositioned. `covered` = already specified in
E0–E25 (cite; do not re-plan). `gap` = planned here. `guidance` = adopted as
written guidance in this RFC, no epic. `rejected` = not adopted.

| # | Concept (best-in-class exemplar) | Disposition | Where |
| --- | --- | --- | --- |
| 1 | Sub-agent context quarantine (Claude Code, Amp) | covered | E2/E3 subflows; §6 |
| 2 | Grader/critic revision loop (Claude Code, Jules) | covered | E23-S2 evaluator-optimizer; E5 |
| 3 | Cross-model second opinion / Oracle (Amp) | gap | E27-S3 |
| 4 | Best-of-N + execution-based selection (Agentless, Codex) | gap | E27-S1 (generalizes E23-S4 race) |
| 5 | Multi-verifier selection, calibrated judges (BoN-MAV) | gap | E27-S2 |
| 6 | Property-based acceptance oracles (CANDOR) | gap | E27-S4 (extends E22 compiler) |
| 7 | Oracle hardening / anti-reward-hacking (UTBoost) | gap | E27-S5 |
| 8 | Decontaminated resource-aware internal evals (SWE-rebench, SWE-Effi) | gap | E27-S5 (shapes E12) |
| 9 | Machine snapshots / environment resume (Devin) | gap | E28-S1 |
| 10 | MicroVM tier for untrusted code (Firecracker/gVisor) | gap | E28-S2 |
| 11 | Browser self-verification (Antigravity, Manus) | gap | E28-S3 |
| 12 | Code-mode MCP / tools as code APIs (Anthropic) | gap | E28-S4 |
| 13 | KV-cache-aware runtime invariants (Manus) | gap | E26-S1 |
| 14 | Condensers / progressive compaction (OpenHands, Claude Code) | gap | E26-S2 |
| 15 | Tool masking over removal (Manus) | gap | E26-S3 |
| 16 | Filesystem/State-Store external memory, reversible compression (Manus, Anthropic) | gap | E26-S4 |
| 17 | Plan recitation + keep-errors-in-context (Manus) | gap | E26-S4 (E23 loop-policy options) |
| 18 | Verified skill/playbook library (Voyager, Devin playbooks) | gap | E29-S1 |
| 19 | Incremental playbook curation, no fine-tuning (ACE) | gap | E29-S2 |
| 20 | Progressive-disclosure skill packs (Claude Code Skills) | gap | E29-S3 |
| 21 | Machine-generated repo knowledge / auto-wiki (Devin) | gap | E29-S4 |
| 22 | Pre-run cost estimation, price legibility (HeyGen, Flow) | gap | E30-S1 |
| 23 | Hierarchical budget caps, checkpoint ceilings, kill switches (enterprise consensus) | gap | E30-S2 (extends ADR-006) |
| 24 | Draft-vs-final execution tiers (HeyGen, Suno pipelines) | gap | E30-S3 (extends E5) |
| 25 | Per-surface metering / billing pools (HeyGen) | gap | E30-S4 |
| 26 | Library spec registry / spec-as-lockfile (Tessl) | gap | E31 |
| 27 | Checkpoints + rewind, HITL pause (Claude Code, LangGraph) | covered | E3-S3, E16-S2 |
| 28 | Plan mode / reviewable plan preview (Windsurf, Cline) | covered | E16-S2, E17 |
| 29 | Artifact/evidence-based verification (Antigravity) | covered | E22-S5 evidence bundles |
| 30 | Event-stream run log (OpenHands) | covered | E9 events; E8-S2 Event Store |
| 31 | AGENTS.md / steering export (Codex, Kiro) | covered | E20 constitution export |
| 32 | EARS specs, drift gate, spec deltas (Kiro, OpenSpec) | covered | E20–E22 |
| 33 | Worktree isolation, task claiming, candidate race (Cursor) | covered | E23-S4 (raced N→1; selection generalized by E27-S1) |
| 34 | Hybrid retrieval: embeddings + symbols + lexical (Cursor) | covered | E7 |
| 35 | Deterministic lifecycle hooks (Claude Code hooks, Kiro) | covered | validation gates (§12.5), plugin permission broker (E1); event triggers via E9 |
| 36 | Model-agnostic provider layer, BYO-LLM (ElevenLabs, OSS tier) | covered | E2-S4, E5 |
| 37 | One engine, many surfaces (HeyGen, §2.13) | covered | §2.13; metering per surface → E30-S4 |
| 38 | Non-destructive scoped edits vocabulary (Midjourney, Flow) | covered | patch workflow §12.2 |
| 39 | Simple-default + custom escape hatch (Suno) | covered | E14 execution modes; E16 chat→plan |
| 40 | Multi-agent restraint, explicit completion contracts (MAST) | guidance | this RFC; harness defaults in E23 ADR |
| 41 | Benchmark skepticism; disclose-the-harness (arXiv 2605.23950) | guidance | this RFC; E27-S5 methodology |
| 42 | Provenance-by-design, default-private sharing (Udio/Midjourney lessons) | guidance | E13/E25/E31-S4 acceptance criteria |
| 43 | Swarm-by-default / large agent fleets | rejected | see below |
| 44 | Spec-as-source (code as build artifact) | rejected | RFC-007 posture stands |
| 45 | Fine-tuning-based agent improvement | rejected | see below |

## Contract surface (overview — per-epic ADRs refine)

New extension-point kinds (RFC-001 catalog, additive):

- **`condenser`** — context-compaction policy invoked by the Agent Runtime
  before an LLM call when thresholds trip (E26-S2); reference impls:
  threshold summarization, progressive compaction.
- **`cost_estimator`** — pre-run estimation strategy consulted by
  `/v2/estimates` (E30-S1).

Extended contracts (additive MINOR): `harness.yaml` `context` strategy gains
condenser/external-memory parameters and loop-policy options `recitation` and
`keep_errors` (E26-S4); E5 Selector policy vocabulary gains `tier:
draft|final` and `distinct_provider_from: <role>` (E27-S3, E30-S3); `skill`
packs gain a progressive-disclosure descriptor (E29-S3).

New `/v2` surfaces (additive, §14.1 conventions): `/v2/estimates` (E30-S1),
`/v2/snapshots` (E28-S1), `/v2/knowledge` (skill/playbook library, E29),
`/v2/library-specs` (E31). New event families (append-only): `candidate.*`
(E27), `snapshot.*` (E28), `knowledge.*` (E29), `cost.*` (E30),
`library_spec.*` (E31).

Contract rules (inherited unchanged from RFC-007): additive-only; external
validation gates "done"; published versions immutable + run version-freezing;
API-first (§2.13); tiered enforcement with recorded waivers; determinism
boundary (ADR-005) extended to cost estimation and snapshot resolution.

## Guidance adopted without epics

1. **Multi-agent restraint** — default topology is one orchestrator + the
   minimum number of verified workers; every inter-agent handoff carries an
   explicit completion contract (what "done" means, verified by whom);
   fan-out breadth is a budgeted, observable parameter, never emergent.
2. **Benchmark discipline** — public benchmark claims are recorded with the
   harness disclosed; internal quality tracking uses held-out, decontaminated
   tasks scored under token/time budgets (E27-S5 defines the methodology;
   E12 executes it).
3. **Provenance & sharing defaults** — anything shareable (skills, specs,
   patches, playbooks) is private by default, provenance-stamped at creation,
   and licensing metadata is mandatory at publish time (E13/E25/E31 inherit
   this as acceptance criteria).
4. **KV-cache economics awareness** — cached input tokens are ~10x cheaper;
   all runtime/protocol design reviews must state their effect on prefix
   stability (E26-S1 makes this measurable).

## Rejected alternatives

- **Swarm-by-default orchestration** (large agent fleets as the primary
  execution model) — rejected: the MAST evidence attributes most multi-agent
  failures to design/verification, not capacity; costs scale linearly with
  agents while gains plateau. Parallelism remains targeted (E23-S4 races,
  E27-S1 candidates, subflows).
- **Fine-tuning-based agent improvement** — rejected for the platform core:
  breaks model-agnosticism, requires per-model MLOps, and the evidence shows
  context/memory-based improvement (E29) captures most of the gain without
  weight updates. Providers may still be fine-tuned externally; the platform
  contract does not depend on it.
- **Adopting a vendor harness wholesale** (running Claude Code/Codex CLI as
  the execution engine) — rejected: surrenders the model-agnostic control
  plane, durable-state governance, and API-first posture; we integrate their
  *concepts* and interoperate via MCP/AGENTS.md instead.
- **Replacing Docker with microVMs everywhere** — rejected: measured overhead
  and operational burden are not justified for trusted validation workloads;
  E28-S2 adds a *tiered* policy (microVM class for untrusted/LLM-generated
  code) instead.
- **A separate "memory service" subsystem** — rejected: E29 persists skills/
  playbooks/knowledge in the existing State Store + pgvector + MinIO stack;
  a new subsystem would violate the OSS-first, minimal-moving-parts posture.

## Rollout

1. **RFC review** — Draft → Under review → Accepted per §19.3 before any E26+
   story starts.
2. **Per-epic ADRs** — E26 (runtime context contract & condenser boundary),
   E27 (candidate/verifier contracts, judge calibration policy), E28
   (snapshot format & isolation-tier policy), E29 (knowledge/skill-library
   schema & curation loop), E30 (estimation model & metering semantics), E31
   (library-spec format & acquisition pipeline).
3. **Sequencing** — E26 and E30 can start once E2/E3 are stable (no v2.1
   dependency); E27 follows E22/E23 contracts (and E14/E12 for
   execution-dependent stories); E28 follows E14; E29 follows E6/E7; E31
   follows E20 (registry pattern) and feeds E13. The v2.2 execution critical
   path therefore still runs through finishing **E14, E12, and E11** — the
   same pressure RFC-007 flagged.
4. **Wave** — delivered as **v2.2 — Concept Integration** (§18.9), after the
   v2.1 wave; E26-S1 (invariants + metric) and E30-S1 (estimation) may start
   earlier since they touch no v2.1 exit criterion.

## References (research annex)

Platform sources (July 2026 pass; RFC-007 annex covers the harness/SDD set):

- Anthropic — autonomous Claude Code (Dynamic Workflows, Performance
  Outcomes): <https://www.anthropic.com/news/enabling-claude-code-to-work-more-autonomously>
- Anthropic — Effective context engineering for AI agents:
  <https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents>
- Anthropic — Code execution with MCP:
  <https://www.anthropic.com/engineering/code-execution-with-mcp>
- Anthropic — Agent Skills:
  <https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills>
- Manus — Context Engineering for AI Agents:
  <https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus>
- Devin 2026 release notes (snapshots, playbooks, knowledge, wiki):
  <https://docs.devin.ai/release-notes/2026>
- Cognition — How Cognition uses Devin to build Devin:
  <https://cognition.com/blog/how-cognition-uses-devin-to-build-devin>
- GitHub — Copilot coding agent:
  <https://docs.github.com/copilot/concepts/agents/coding-agent/about-coding-agent>
- Google — Jules: <https://blog.google/innovation-and-ai/models-and-research/google-labs/jules/>
- Amp Owner's Manual (the Oracle, threads): <https://ampcode.com/manual>
- Factory 2.0 (coordinator + droids): <https://factory.ai/news/software-factory>
- Warp open-sources its ADE:
  <https://www.warp.dev/newsroom/2026/4/28/warp-open-sources-its-agentic-development-environment>
- OpenHands SDK (event stream, condensers): <https://arxiv.org/html/2511.03690v1>
- Aider repository map: <https://aider.chat/docs/repomap.html>
- Tessl — spec-driven framework + registry:
  <https://tessl.io/blog/tessl-launches-spec-driven-framework-and-registry/>
- Martin Fowler — exploring SDD tools:
  <https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html>
- ElevenLabs — agents orchestration engine:
  <https://elevenlabs.io/blog/unpacking-elevenagents-orchestration-engine>
- HeyGen — API pricing model: <https://developers.heygen.com/docs/pricing>
- Google Flow / Veo: <https://blog.google/technology/ai/google-flow-veo-ai-filmmaking-tool/>
- Northflank — sandboxing AI agents (microVM guidance):
  <https://northflank.com/blog/how-to-sandbox-ai-agents>

Academic (grouped; key items):

- Scaffolds & interfaces: SWE-agent ACI <https://arxiv.org/abs/2405.15793>;
  AutoCodeRover <https://arxiv.org/abs/2404.05427>; Agentless
  <https://arxiv.org/abs/2407.01489>; LocAgent <https://arxiv.org/abs/2503.09089>.
- Evaluation discipline: OpenAI — Why we no longer evaluate SWE-bench
  Verified <https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/>;
  memorization study <https://arxiv.org/html/2512.10218v2>; UTBoost
  <https://arxiv.org/pdf/2506.09289>; SWE-rebench <https://arxiv.org/pdf/2505.20411>;
  SWE-bench Pro <https://arxiv.org/abs/2509.16941>; SWE-Effi
  <https://arxiv.org/html/2509.09853v2>; "Building to the Test"
  <https://arxiv.org/pdf/2606.28430>; lucky-pass analysis
  <https://arxiv.org/html/2605.12925v1>.
- Verification & test-time compute: RLEF <https://www.arxiv.org/pdf/2410.02089>;
  RLVR/GRPO analysis <https://arxiv.org/html/2503.06639v4>; dense verifiable
  rewards <https://arxiv.org/pdf/2601.03525>; certified self-consistency
  <https://arxiv.org/html/2510.17472v2>; judge self-inconsistency
  <https://arxiv.org/pdf/2510.27106>; judge design study
  <https://arxiv.org/html/2506.13639v1>; calibrated judge compute
  <https://arxiv.org/html/2512.03019v2>.
- Property-based oracles: Property-Generated Solver
  <https://arxiv.org/html/2506.18315v1>; CANDOR <https://arxiv.org/html/2506.02943v2>;
  agentic PBT <https://arxiv.org/pdf/2510.09907>.
- Memory & self-improvement: ACE <https://arxiv.org/abs/2510.04618>;
  MUSE-Autoskill <https://arxiv.org/html/2605.27366v1>; Evo-Memory
  <https://arxiv.org/pdf/2511.20857>; agent-memory survey
  <https://arxiv.org/html/2603.07670v1> (Reflexion/Voyager foundational).
- Multi-agent: MAST failure taxonomy <https://arxiv.org/abs/2503.13657>;
  single-LLM multi-agent scaling <https://arxiv.org/pdf/2606.00655>;
  AgentDropout <https://arxiv.org/pdf/2503.18891>.
- Context engineering: PEEK context map <https://arxiv.org/pdf/2605.19932>;
  compaction/long-horizon memory <https://arxiv.org/pdf/2605.08580>.
- Repo intelligence: RANGER <https://arxiv.org/abs/2509.25257>; tree-sitter
  knowledge graphs <https://arxiv.org/pdf/2603.27277>; LARGER
  <https://arxiv.org/pdf/2605.16352>; repo-RAG survey
  <https://arxiv.org/pdf/2510.04905>.
- Security: injection on coding assistants <https://arxiv.org/html/2601.17548v1>;
  injection threat landscape <https://arxiv.org/pdf/2602.10453>; MAC for
  agents <https://arxiv.org/pdf/2601.11893>; Progent (arXiv:2504.11703);
  SAGA (arXiv:2504.21034); sandboxed agents competitive
  <https://arxiv.org/pdf/2606.00579>.
- SDD research: SpecGen (ICSE 2025)
  <https://dl.acm.org/doi/10.1109/ICSE55347.2025.00129>; spec-driven
  governance <https://arxiv.org/pdf/2605.01160>; SANER'26 registered report
  <https://arxiv.org/pdf/2601.03878>.

## Open questions

- **E26**: is the KV-cache hit-rate metric computable provider-agnostically
  (from usage fields) or does it need per-provider adapters? Which condenser
  triggers ship as defaults (event count vs token budget vs cost)?
- **E27**: candidate race budget semantics — N candidates within the parent
  budget (ADR-006) or an explicit multiplier? Minimum verifier set for a
  candidate to be selectable? When both are configured, does the cross-model
  oracle vote or veto?
- **E28**: snapshot format — image layers in MinIO vs registry-backed OCI
  images? Which isolation class is the default for `execution_mode: auto`
  runs? Does browser verification ship as a `skill` or a sandbox runner
  profile?
- **E29**: what promotes a run artifact into the skill library — gate
  verdicts alone or human curation? Retention/decay policy for stale
  playbooks? Interop: import Claude-Code-style SKILL.md packs as-is?
- **E30**: estimation before execution is inherently approximate — what error
  band is acceptable before estimates are misleading (and must the UI show
  confidence)? Are billing pools per surface, per tenant, or both?
- **E31**: seed strategy for the registry (generate from installed deps on
  first index vs curated seed set)? Trust model for shared library specs
  (signature chain from E13 or independent)?
