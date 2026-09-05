# E63 — Flow Applicability and Task-Intent Execution Routing

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E62).
**Status:** Not started · **Stories:** 0/5
**Depends on:** E62-S1/S3 (a resolved project whose real state can be probed),
E3 (Flow Engine, complete and tested), E5 (Router/Selector contracts),
E2 (Agent Registry)
**Enables:** the platform choosing *how* to work on a task instead of always
doing the same thing — the defect that makes every request, however small,
re-open architecture decisions.
**Canonical source:** this document, plus direct inspection of
`backend/flows/`, `backend/orchestrator/service/` and `backend/routing/`
(2026-09-05).

## Context and problem

Flows are a finished subsystem with no content and no entry point, and the
product path ignores them entirely.

**No flow is shipped.** No `flow.yaml` exists anywhere in the repository.
`FlowRegistry` is empty until someone `POST /v2/flows` a manifest; nothing seeds
it at startup. The only flow documents that exist are
`docs/v2_platform/templates/manifests/flow.yaml.example`, which no code loads,
and `frontend/lib/flow/sample.ts`'s `SAMPLE_FLOW`, which the visual editor loads
as its default document.

**No flow is selected.** `grep -rni "select_flow|flow_selector|choose_flow|
flow_router"` returns nothing. Selection is entirely manual: the caller names
the flow in the URL path (`POST /v2/flows/{namespace}/{name}/runs`,
`backend/api/routers/flows.py:363`). The `trigger` endpoint checks that a flow
*declares* a trigger type — authorization, not matching.

**A flow cannot describe when it applies.** `FlowManifest`
(`backend/flows/model.py:220-254`) carries `name` and `description` as free text
— `docs/flows/spec.md` calls them "Display metadata" — plus `input`/`output`
JSON Schemas, `triggers`, `defaults` and `budgets`. There is no field for
purpose, for when a flow should be used, or for when it should not be. The
catalog (`backend/flows/registry.py:131-159`) emits even less. So even a perfect
selector would have nothing structured to reason over.

**The real path never varies.** `OrchestratorService` compiles a strictly linear
LangGraph from `OrchestratorConfig.agent_order = (navigator, analyzer,
architect, coder, devops, validator, responder)`
(`backend/orchestrator/service/models.py:246-258`,
`backend/orchestrator/service/graph.py:68-82`) — entry is `order[0]`, one edge
per consecutive pair, no conditionals. **Every chat turn runs all seven,
`architect` included**, whatever the user asked for. There is no path from chat
to `FlowEngine`: `grep "start_run(|FlowEngine("` outside `backend/flows/` and
tests returns only `backend/api/routers/flows.py`.

**The machinery to fix it exists and is deliberately unplugged.**
`_infer_run_type` (`backend/orchestrator/service/core.py:149-169`) is a
substring heuristic over the goal and message — `"doc" in combined` matches
"add a docker healthcheck" — and its only uses are a persisted label and the
synthetic trace id `flow_id = f"orchestrator.{run_type}"`, which is not a
registry flow. `RunTypeRouter` (`backend/orchestrator/routing.py:36-59`) *does*
map a run type to an agent order, and its own module docstring says:

> "This module is STANDALONE — it is NOT wired into the default `/chat` path."

It is reachable only through `POST /chat/dynamic` behind `AUTODEV_DYNAMIC_ORCH=1`,
and even there `GREENFIELD_BOOTSTRAP`, `EXISTING_REPO_CHANGE` and
`PLAN_EXECUTION` all map to the full order, so `architect` still always runs.
`backend/routing/` (E5) is a task/agent/model router with rules-only stages
(`embeddings` and `llm-router` raise "has no backend in E5-S1"), whose
`RouteDecision.path` is documented as possibly naming flows but in practice
always names agents — and which has **no non-test consumer** outside its own
`POST /v2/route` and `POST /v2/select` endpoints.

**Project state does not exist as a signal.** `RunType.GREENFIELD_BOOTSTRAP` is
derived only from the words "bootstrap", "greenfield", "new project" or "from
scratch" appearing in the text — never from looking at the filesystem.
`ContextDigest`/`ContextSignals` (`backend/routing/contract.py:69-92`) have
exactly the right shape (`repo`, `has_tests`, `languages`) and are documented as
"summarized by the Context/RAG Service", but nothing produces them; they are
populated only by whatever a caller passes in.

## Evidence in code and documentation

- `backend/flows/model.py:220-254` — `FlowManifest`, the complete field set.
- `backend/flows/manifest.py:264-332` — the parser, which reads exactly those
  keys; `backend/flows/schemas/flow.schema.json` — `additionalProperties: true`,
  so a new key would validate and then be silently dropped into `raw`.
- `backend/flows/registry.py:81-101` — `resolve` (SemVer, the only "selection"
  that exists); `:131-159` — the catalog projection.
- `backend/api/routers/flows.py:363` — `POST /v2/flows/{ns}/{name}/runs`;
  `:409` — `trigger`; `:112` — the cron tick, the only automatic start.
- `backend/orchestrator/service/models.py:246-258` — `agent_order`.
- `backend/orchestrator/service/graph.py:68-82` — `_compile_graph`, linear.
- `backend/orchestrator/service/core.py:149-169` — `_infer_run_type`.
- `backend/orchestrator/service/chat.py:107,117-123` — the synthetic
  `orchestrator.<run_type>` flow id emitted as `flow.run.started`.
- `backend/orchestrator/routing.py:1-8,36-59` — `RunTypeRouter` and its
  "NOT wired" docstring; `backend/orchestrator/graphs.py:1-8` — the same.
- `backend/routing/router.py:135-152,191-220` — the rules-only pipeline;
  `backend/routing/policy.py:327-344` — `generic_router_default()`, the fallback
  to the full seven-agent order.
- `backend/routing/contract.py:69-92,146` — `ContextDigest`/`ContextSignals`
  and `RouteDecision.path`.
- `backend/agents/capabilities.py` — the closed five-capability vocabulary;
  `examples/plugins/agent-coder/agent.yaml` — the only shipped `agent.yaml`.
- `docs/v2_platform/decisions/RFC-002-flow-yaml-spec.md`,
  `ADR-004-flow-manifest-and-node-types.md` — the manifest's governing decisions.

## Objective

Let a flow declare when it applies, let the platform judge applicability against
the task's intent and the project's real state, and let it execute directly when
no flow fits — instead of always running one fixed pipeline.

## Key result

Asking for a small change in an existing project does not run the structuring
flow and does not run the architect; asking to start a new project does select
the bootstrap flow; and a task with no matching flow is planned and executed
directly, with the decision and its reason recorded.

## Scope

- Additive manifest fields declaring purpose, applicability and preconditions.
- Exposure of the declared inputs and outputs in the flow catalog.
- A deterministic probe of the project's real state.
- A two-phase selector: deterministic elimination, then a constrained model
  choice among survivors, with "none" as a first-class outcome.
- Wiring the chat entrypoint to the selection result, including the direct
  execution path.
- Two built-in flows shipped and seeded.

## Out of scope

- Rebuilding `backend/routing/` (E5) or implementing its `embeddings` /
  `llm-router` stages — this epic reuses `ContextSignals` and `RunTypeRouter`,
  and does not extend the E5 pipeline.
- A capability-based agent marketplace or new `agent.yaml` manifests for the
  eleven built-in v1 agents — a real gap, but E13/E25 territory.
- Sub-flow composition, new node types, or any change to the flow execution
  engine. This epic changes selection, not execution.
- Removing `POST /chat/dynamic`; it becomes redundant but its removal is a
  separate deprecation.

## Stories

### E63-S1 — Applicability declaration in the manifest (schema 2.1, additive)

Subtasks:
- `E63-S1-T1`: add `purpose`, `whenToUse`, `whenNotToUse` and `requires` to the
  flow manifest — the first three as human- and model-readable text, `requires`
  as structured preconditions over the project-state vocabulary E63-S2 defines.
  Parsed into `FlowManifest`, validated in `backend/flows/manifest.py`, and
  declared in `backend/flows/schemas/flow.schema.json`.
- `E63-S1-T2`: surface `purpose`/`whenToUse`/`whenNotToUse` and the already-
  existing `input`/`output` schemas in the registry catalog projection
  (`backend/flows/registry.py:131-159`), which today emits only
  id/version/name/description/hostApi/triggers/node count — so a client, and the
  selector, can see what a flow needs and produces without loading the manifest.
- `E63-S1-T3`: keep 2.0 manifests valid. The JSON Schema is already
  `additionalProperties: true` and the new fields are optional; a flow that
  declares none is simply never *automatically* selected, and stays explicitly
  runnable. State that rule in `docs/flows/spec.md` rather than leaving it
  implicit.

| Criterion | Detail |
| --- | --- |
| Functional | A manifest can declare purpose, when to use, when not to use, required inputs and produced outputs, and all of it is readable from the catalog |
| Non-functional | Additive: every existing 2.0 manifest parses and runs unchanged |
| DoR (specific) | The state vocabulary `requires` refers to is agreed with E63-S2 |
| DoD (specific) | A 2.0 manifest round-trips unchanged; a 2.1 manifest exposes the new fields in the catalog; an invalid `requires` fails validation with a field-path message |
| Dependencies | E3 |

### E63-S2 — Deterministic project-state probe

Subtasks:
- `E63-S2-T1`: a new `backend/projects/state.py` producing a typed snapshot of
  the resolved project root: empty versus populated, Git present, tests present,
  languages detected. Pure filesystem inspection — no LLM, no network, no
  database.
- `E63-S2-T2`: populate `ContextDigest`/`ContextSignals`
  (`backend/routing/contract.py:69-92`) from that snapshot, giving the existing,
  already-modelled contract its first real producer instead of adding a parallel
  one.
- `E63-S2-T3`: bound the cost. The probe runs on every turn, so it prunes
  ignored directories during traversal the way `backend/repository/indexing.py`
  already does (E45), and caches per project root with invalidation on change.

| Criterion | Detail |
| --- | --- |
| Functional | The probe distinguishes an empty directory, a populated project without Git, and a populated project with Git and tests |
| Non-functional | Deterministic and offline; bounded traversal cost on a large repository |
| DoR (specific) | E62-S3 merged (there is a per-session root to probe) |
| DoD (specific) | Tests over three fixture trees; a test that the probe never descends into ignored directories |
| Dependencies | E62-S3 |

### E63-S3 — `FlowSelector`

Subtasks:
- `E63-S3-T1`: a new `backend/flows/selection.py` implementing phase one — the
  **deterministic gate**: discard every flow whose `requires` or `whenNotToUse`
  conflicts with the probed project state. This is the gate that structurally
  prevents a bootstrap flow from being chosen in a populated project; it does not
  depend on a model judging correctly.
- `E63-S3-T2`: phase two — a **constrained choice** among the survivors, given
  only `purpose`/`whenToUse`/`whenNotToUse`/`input` and the task text, with
  `"none"` a valid answer. Fail closed to `"none"` on any error, timeout or
  unparseable response: the absence of a flow is a supported outcome, so falling
  back to it is never a degradation.
- `E63-S3-T3`: when a genuinely essential input for the chosen flow is missing,
  return a single targeted question instead of guessing — the selector asks for
  exactly the missing item, and asks nothing else.
- `E63-S3-T4`: record the decision durably: new catalog events
  `flow.selection.matched` and `flow.selection.skipped`, each carrying the
  candidates considered, the eliminating rule where one applied, and the reason.
  Appended to `EVENT_CATALOG`, past-tense `domain.entity.action`, as the
  convention requires.

| Criterion | Detail |
| --- | --- |
| Functional | A flow incompatible with the project state is eliminated before any model sees it; "none" is returned when nothing fits; a missing essential input produces one question |
| Non-functional | Fail-closed to "none"; every decision is reconstructible from durable events alone |
| DoR (specific) | E63-S1 and E63-S2 merged |
| DoD (specific) | A test that a bootstrap-flow candidate is eliminated by the gate in a populated project **with the model stubbed to choose it** — proving the gate, not the prompt; a test that a provider error yields "none" |
| Dependencies | E63-S1, E63-S2 |

### E63-S4 — Wire the chat entrypoint

Subtasks:
- `E63-S4-T1`: `handle_message` consults the selector: a chosen flow starts a
  `FlowEngine` run; `"none"` takes the direct execution path. This is the first
  code path from chat to the Flow Engine.
- `E63-S4-T2`: the direct path uses an agent order appropriate to the intent
  instead of the fixed seven — replacing `_infer_run_type`'s substring heuristic
  with `RunTypeRouter`, which already exists, is already tested
  (`backend/tests/unit/orchestrator/test_orchestrator_routing.py`), and is
  explicitly documented as not wired. **A change in an existing project does not
  run `architect`.**
- `E63-S4-T3`: preserve every existing capability — plan creation, plan
  execution, self-repair, quota leasing, the `flow.run.started` envelope and the
  timeline events all continue to work on both branches. `AUTODEV_DYNAMIC_ORCH`
  becomes unnecessary; document that rather than silently ignoring the flag.

| Criterion | Detail |
| --- | --- |
| Functional | Chat can run a flow, or execute directly; the path taken follows intent and project state |
| Non-functional | No existing chat capability regresses; both branches emit the same run/event contract |
| DoR (specific) | E63-S3 merged |
| DoD (specific) | Three invariant tests: (i) "add a button to view logs" in a populated project runs neither the bootstrap flow nor `architect`; (ii) a task with no compatible flow executes directly and completes; (iii) an empty project plus "create a new project" selects the bootstrap flow |
| Dependencies | E63-S3 |

### E63-S5 — Ship built-in flows

Subtasks:
- `E63-S5-T1`: package two flows under a new `backend/flows/builtin/`, declared
  with the E63-S1 fields: `autodev/flow-project-bootstrap` (requires an empty or
  unstructured project; explicitly *not* for an existing codebase) and
  `autodev/flow-feature-delivery` (requires an existing project), the latter
  mirroring the already-validated
  `docs/v2_platform/templates/manifests/flow.yaml.example` and the editor's
  `SAMPLE_FLOW` so the three do not drift.
- `E63-S5-T2`: seed them into `FlowRegistry` at startup, idempotently —
  re-seeding an unchanged version is a no-op, and a user-published version of the
  same id is never overwritten, because publishing a new version must never
  mutate an existing one (reference §7.1).
- `E63-S5-T3`: the refs the built-in flows point at must resolve. Where a
  referenced agent or skill is not shipped, either point at one that is or
  declare the gap in the phase record — a flow that cannot run is worse than no
  flow.

| Criterion | Detail |
| --- | --- |
| Functional | A fresh install has at least two selectable flows whose nodes resolve |
| Non-functional | Seeding is idempotent and never overwrites a user-published version |
| DoR (specific) | E63-S1 merged |
| DoD (specific) | A test that seeding twice leaves one registry entry per version; a test that each built-in flow's refs resolve in a default install |
| Dependencies | E63-S1, E63-S4 |

## Contracts and decisions

### Architectural decisions required

- A new ADR is required for the **flow applicability contract**: adding
  `purpose`/`whenToUse`/`whenNotToUse`/`requires` is a MINOR change to a public
  artifact contract (reference §19.1/§19.3, the flow-manifest row), and RFC-002 /
  ADR-004 are its governing decisions. The ADR must state that the deterministic
  gate — not the model — is the enforcement mechanism for applicability, because
  that is the property the whole epic rests on.
- A second decision worth recording in the same ADR: `_infer_run_type` is
  replaced rather than extended, and `RunTypeRouter` moves from standalone to
  default. Its docstring's disclaimer must be removed in the same change, not
  left to contradict the code.

### Security and multitenancy

- The selector sends flow metadata and the task text to a model provider. It
  must not send project file contents, secrets, or the project root path; the
  probe's output is a small typed snapshot, not a directory listing.
- Selection is per tenant: the candidate set is the tenant's resolvable flows,
  scoped the way `FlowRegistry` already scopes them.
- Fail-closed applies in the platform's usual sense: a failure yields *no flow*,
  which is the safe, non-destructive branch — never "run the structuring flow
  because we could not decide".

### Migration strategy

- No schema migration. Manifest schema 2.1 is additive and 2.0 documents remain
  valid, matching how agent manifest 2.1 was introduced in E2-S6.
- Existing runs in progress stay pinned to the flow version they started with
  (reference §7.1); seeding cannot affect them.

### Compatibility and rollback

- Rollback is reverting the entrypoint wiring in E63-S4; the manifest fields,
  the probe and the selector are inert without it.
- Explicit `POST /v2/flows/{ns}/{name}/runs` is unchanged and remains the way to
  run a flow deliberately, including one that declares no applicability.

## Testing and observability

Tests required:
- 2.0 manifest round-trip; 2.1 fields in the catalog; invalid `requires`.
- Probe over empty / no-Git / Git+tests fixture trees, and ignored-directory
  pruning.
- Gate elimination **with the model stubbed to choose the eliminated flow**.
- Fail-closed to "none" on provider error.
- Single targeted question when an essential input is missing.
- The three E63-S4 invariants.
- Idempotent seeding; built-in flow refs resolve.

Observability:
- `flow.selection.matched` / `flow.selection.skipped` make every decision
  auditable from durable records alone — the same standard E32 set for
  reconstructing which backend and profile a run used.
- The existing `flow.run.started` envelope is unchanged; the synthetic
  `orchestrator.<run_type>` id remains for the direct path, so existing trace
  consumers do not break.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| The model picks an inappropriate flow | The exact defect this epic exists to fix, reintroduced one layer up | The deterministic gate runs first and is tested with the model stubbed adversarially (E63-S3-T4 DoD) |
| Selection adds latency to every turn | A slower product for no visible benefit | The probe is cached per root; the model call sees only metadata for the surviving candidates, and is skipped entirely when zero or one survives |
| Dropping `architect` loses genuinely needed design work | Under-designed changes in a codebase that needs the step | `RunTypeRouter`'s mapping decides per run type, and a greenfield or architectural intent still includes it; the change is "not always", not "never" |
| Built-in flows reference agents that do not ship | A selectable flow that cannot run | E63-S5-T3 resolves or declares every ref, with a test |
| Two sources of truth for the feature-delivery flow (docs example, editor sample, built-in) | Silent drift | E63-S5-T1 makes the built-in the source and the others mirror it |

## DoR / DoD

- **DoR:** E62-S3 merged; the flow-applicability ADR written and Accepted; the
  project-state vocabulary agreed between E63-S1 and E63-S2.
- **DoD:** all five story DoDs met; the three E63-S4 invariants green; a fresh
  install ships selectable flows; every selection recorded durably;
  `docs/flows/spec.md`, `docs/flows/engine.md` and
  `docs/v2_platform/progress.md` updated; `RunTypeRouter`'s "NOT wired"
  docstring removed in the same change that wires it.

## Affected documents and code

Documents: `docs/flows/spec.md`, `docs/flows/engine.md`, a new ADR under
`decisions/`, `docs/v2_platform/decisions/README.md` (index),
`docs/v2_platform/progress.md`, `CHANGELOG.md`.

Code: `backend/flows/model.py`, `backend/flows/manifest.py`,
`backend/flows/fields.py`, `backend/flows/registry.py`,
`backend/flows/schemas/flow.schema.json`, `backend/flows/selection.py` (new),
`backend/flows/builtin/` (new), `backend/projects/state.py` (new),
`backend/routing/contract.py`, `backend/orchestrator/service/chat.py`,
`backend/orchestrator/service/core.py`, `backend/orchestrator/service/graph.py`,
`backend/orchestrator/routing.py`, `backend/events/catalog.py`,
`frontend/lib/flow/sample.ts`.
