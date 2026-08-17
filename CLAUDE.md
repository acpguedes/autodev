# CLAUDE.md

Guidance for Claude Code and other AI contributors working in this repository.

## Goal

Evolve AutoDev Architect into a strong open-source, self-hostable AI software engineering platform.

Optimize every change for:

1. correctness;
2. architectural consistency;
3. minimal implementation complexity;
4. fast, focused execution;
5. maintainability.

Do not add work that is not required to complete the requested task.

---

## Core architecture

Prefer:

* API-first design through the versioned Control Plane API (`/v2`);
* PostgreSQL for durable state;
* Redis for queues, cache, and locks;
* pgvector before introducing a dedicated vector database;
* MinIO for artifacts;
* tree-sitter for code intelligence;
* Docker for sandboxed execution;
* FastAPI for the backend Control Plane;
* Next.js for the UI.

Web UI, CLI, MCP, and other clients must use `/v2`. They must not access the State Store or internal services directly.

Canonical architecture:
`docs/architecture/v2_platform_reference.md`

---

## Execution policy

Work toward the requested outcome using the smallest safe number of steps.

Before editing:

1. identify the exact requested outcome;
2. determine the smallest affected code surface;
3. identify relevant contracts, callers, tests, and documentation;
4. make the complete change in as few coherent passes as practical.

During execution:

* Prefer targeted inspection over broad repository exploration.
* Read only files needed for the current task.
* Do not reread unchanged files unless previous context is insufficient.
* Reuse command, test, search, and tool output already obtained.
* Do not repeat a command unless repository state changed or the previous result was inconclusive.
* Do not run multiple tools that answer the same question without a specific reason.
* Avoid speculative refactors, cleanup, or unrelated improvements.
* Do not create abstractions unless the current change needs them.
* Do not narrate routine actions or produce long intermediate summaries.
* Do not ask the user for information that can be reliably obtained from the repository.
* If a reasonable implementation choice can be made from existing architecture and conventions, make it and proceed.
* Stop when the requested behavior is implemented and sufficiently verified.

Correctness takes precedence over speed, but additional work must have a concrete justification.

---

## Repository exploration

This repository has a knowledge graph.

### Preferred order

When code-review-graph MCP tools are available, use them before Grep/Glob/broad file reads.

Use:

| Need                          | Preferred tool                   |
| ----------------------------- | -------------------------------- |
| Find relevant code            | `semantic_search_nodes_tool`     |
| Trace callers/dependencies    | `query_graph_tool`               |
| Estimate blast radius         | `get_impact_radius_tool`         |
| Find affected execution paths | `get_affected_flows_tool`        |
| Review changes                | `detect_changes_tool`            |
| Get focused review source     | `get_review_context_tool`        |
| Understand architecture       | `get_architecture_overview_tool` |
| Plan refactors                | `refactor_tool`                  |

Typical implementation flow:

1. locate the affected code;
2. inspect impact/dependencies;
3. read only the necessary source;
4. implement;
5. inspect the resulting diff/affected flows;
6. run focused verification.

Fall back to Grep/Glob/Read when the graph does not contain enough information.

### Graphify CLI fallback

If MCP graph tools are unavailable and `graphify-out/graph.json` exists:

```bash
graphify query "<question>"
graphify path "<A>" "<B>"
graphify explain "<concept>"
```

Use `graphify-out/wiki/index.md` for broad navigation.

Read `graphify-out/GRAPH_REPORT.md` only for broad architectural analysis or when focused graph queries are insufficient.

After code changes, if graph auto-update hooks are not active:

```bash
graphify update .
```

Do not use both MCP graph exploration and equivalent Graphify CLI queries unless one fails to provide the required context.

---

## Development environment

For commands that depend on project Python packages, always use the project virtualenv:

```bash
source .venv/bin/activate && <command>
```

This includes:

* Python scripts;
* tests;
* linters;
* migrations;
* backend execution;
* `python`;
* `pip`.

If `.venv` does not exist:

```bash
python -m venv .venv
source .venv/bin/activate
```

Then install only the dependencies required by the project setup.

Do not recreate or reinstall the environment when an existing working environment is available.

---

## Implementation quality

For new or modified Python public APIs:

* use complete type hints;
* use English docstrings where required by project conventions;
* document description, arguments, return values, and relevant exceptions.

For machine-readable interfaces:

* use explicit schemas and structured outputs;
* keep user-facing content separate from control metadata.

For new subsystems or meaningful architecture changes:

* explain why the subsystem belongs in the architecture;
* document the problem it solves;
* update the appropriate documentation.

Follow existing patterns before inventing new ones.

---

## Testing and verification

Use the **smallest verification that proves the current change works**.

### Story work

Run:

1. tests directly related to changed behavior;
2. tests for affected shared contracts only when the change can impact them;
3. targeted lint/type/static checks when relevant.

Do **not** routinely run the entire repository test suite for a story.

Do not rerun successful tests unless:

* relevant code changed afterward;
* configuration/environment changed;
* the previous result was incomplete or ambiguous.

When fixing a failing test:

1. run the failing test or smallest relevant test group;
2. implement the fix;
3. rerun that same scope;
4. expand verification only if the change has a wider demonstrated impact.

Do not repeatedly run broader suites "for confidence" without evidence that they are needed.

### Epic completion

The full suite is required only for the epic → `main` PR:

```bash
make check
```

If `make check` succeeds and no code changes occur afterward, do not run it again.

If it fails, rerun only the failing checks while fixing them, then run `make check` once after the fixes are complete.

---

## Git workflow

`CONTRIBUTING.md` is canonical.

### Branches

Epic:

```text
epic/e<N>-<slug>
```

created from `main`.

Story:

```text
story/e<N>-s<M>-<slug>
```

created from its epic branch.

### Story completion

After a story is implemented and its focused verification passes:

1. merge the story branch into the epic branch;
2. push the epic branch;
3. delete the merged story branch.

Do not run epic-wide validation at every story boundary unless the story changes a shared contract with broad impact.

### Epic completion

After all epic stories are complete:

1. update the tracker/docs;
2. run `make check`;
3. push the epic branch;
4. open the epic → `main` PR;
5. merge through the PR;
6. sync local `main`;
7. delete merged story and epic branches locally and remotely.

Do not merge an epic directly into `main`.

---

## Planning and model usage

For non-trivial Claude Code tasks:

* use Opus for planning when planning is needed;
* execute implementation directly with Sonnet.

Do not hand work to Codex unless the user explicitly requests Codex.

Planning should be proportional to the task. Do not produce a large plan for a small or obvious change.

A plan should identify only:

* intended outcome;
* affected components;
* implementation sequence;
* necessary verification.

Once sufficient context exists, execute rather than continuing to analyze.

Keep `AGENTS.md` consistent with these rules.

---

## v2 implementation

The v2 platform is defined by:

* `docs/architecture/v2_platform_reference.md`
* `docs/v2_platform/progress.md`
* `docs/v2_platform/agent_guide.md`

Before implementing an `E<n>-S<m>` story, read the relevant portion of `agent_guide.md` and the corresponding epic/story information.

Do not reread the complete platform documentation if the relevant scope is already known.

For Alpha/Beta/GA wave exits, follow:

`docs/v2_platform/documentation_rebuild.md`

---

## Continuation commands

Resolve terse continuation requests against:

`docs/v2_platform/progress.md`

Treat the tracker as canonical, but verify suspicious or inconsistent status against the code before implementing anything.

### "continue a implementação" / "next stage|phase|epic"

Select the next eligible epic in this order:

1. unfinished Beta;
2. v2.1;
3. v2.2.

Respect dependencies.

Inside the epic, execute unfinished stories in dependency order, normally `S1 → Sn`.

If multiple epics are equally eligible, choose the one that unlocks the most downstream work and state the reason briefly.

Do not ask the user which eligible story to choose unless the tracker provides no defensible choice.

### "feche os gaps" / "execute stories abertos"

Do not start a new epic.

Instead:

1. find incomplete stories inside already-started epics;
2. compare tracker status with implementation;
3. implement genuinely missing work in dependency order.

If code already implements a supposedly missing story, update the tracker rather than reimplementing it.

If the tracker says a story is complete but required behavior is demonstrably absent, treat it as a gap and report the inconsistency briefly.

---

## Completion protocol

A task is complete when:

* requested behavior exists;
* relevant contracts remain valid;
* the smallest sufficient verification passes;
* required docs/tracker updates are made;
* required Git workflow steps for the requested scope are complete.

Once these conditions are proven, stop.

Do not perform additional repository scans, tests, reviews, refactors, or confirmation passes unless a concrete unresolved risk remains.

Final reports should be concise and contain only:

* what changed;
* verification performed;
* any important unresolved issue.

Do not repeat information already obvious from the diff or command output.

