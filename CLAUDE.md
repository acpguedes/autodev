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
* Read only files required for the current task.
* Do not reread unchanged files unless existing context is insufficient.
* Reuse command, test, search, and tool output already obtained.
* Do not repeat a command unless repository state changed or the previous result was inconclusive.
* Do not use multiple tools to answer the same question without a concrete reason.
* Avoid speculative refactors, cleanup, or unrelated improvements.
* Do not create abstractions unless the current change requires them.
* Do not narrate routine actions or produce long intermediate summaries.
* Do not ask the user for information that can be reliably obtained from the repository.
* If existing architecture and conventions provide a reasonable implementation choice, make it and proceed.
* Prefer completing a coherent implementation slice before performing broader validation.
* Stop as soon as the requested outcome is implemented and the minimum sufficient verification proves it works.

Correctness takes precedence over speed, but every additional action must have a concrete justification.

---

## Repository exploration

This repository has a knowledge graph.

### Preferred order

When code-review-graph MCP tools are available, use them before Grep/Glob/broad file reads.

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
2. inspect relevant impact/dependencies;
3. read only the necessary source;
4. implement;
5. inspect the resulting diff or affected flows when useful;
6. run focused verification.

Fall back to Grep/Glob/Read only when the graph does not provide enough context.

### Graphify CLI fallback

If MCP graph tools are unavailable and `graphify-out/graph.json` exists:

```bash
graphify query "<question>"
graphify path "<A>" "<B>"
graphify explain "<concept>"
```

Use `graphify-out/wiki/index.md` for broad navigation.

Read `graphify-out/GRAPH_REPORT.md` only for broad architecture analysis or when focused graph queries are insufficient.

After code changes, if graph auto-update hooks are not active:

```bash
graphify update .
```

Do not run equivalent MCP graph and Graphify CLI queries unless the first method fails to provide required context.

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

Then install the dependencies required by the project setup.

Do not recreate or reinstall a working environment.

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

## Verification economy

Verification is **incremental, minimal, and non-cumulative**.

The purpose of testing during implementation is to prove the behavior just changed, not to repeatedly revalidate the repository.

### Default rule

After an implementation step, run the smallest test that directly exercises the changed behavior.

Prefer, in order:

1. one relevant test case;
2. one focused test file;
3. a narrowly related test group only when required by the change's actual blast radius.

Do not automatically escalate from:

* one test → full test file;
* one test file → package suite;
* package suite → related packages;
* related packages → broad touched-surface suite;
* touched-surface suite → full repository suite.

A successful focused test is sufficient evidence for that implementation step unless a concrete unresolved risk remains.

### When broader testing is justified

Expand test scope only when at least one of these conditions is true:

* the change modifies a shared contract used outside the directly tested component;
* imports, dependency injection, configuration, serialization, persistence, or another integration boundary changed;
* a targeted test exposes evidence of a wider failure;
* impact analysis identifies concrete downstream consumers that require verification;
* the task has reached an explicit integration, story, or epic gate that requires broader validation.

The reason for expanding the test scope must come from the change itself, not from generic caution.

### Forbidden verification patterns

Do not run broader tests merely:

* "to ensure nothing else broke";
* "for confidence";
* "as a sanity check";
* "just in case";
* "once more";
* because a commit is about to be created;
* because the previous focused tests passed;
* because a broader suite exists.

Commits are not verification boundaries.

Do not run additional tests solely before or after a commit if the relevant code and environment have not changed.

Do not rerun already-passing tests unless:

* relevant code changed afterward;
* relevant configuration or dependencies changed;
* the previous execution was incomplete or ambiguous;
* a later failure provides evidence that the previously tested area may now be affected.

### Failure handling

When a test fails:

1. identify the smallest relevant cause;
2. modify the required code;
3. rerun the failing test or smallest failing scope;
4. stop expanding once the failure is resolved.

If a broader suite exposes a failure outside the original focused scope, fix that failure using its smallest targeted test before rerunning the broader suite.

Do not repeatedly rerun the broader suite while debugging individual failures.

### Story verification

During a story, test each implementation slice only at the scope needed to prove that slice.

At story completion:

* do not rerun all previously passing tests by default;
* do not create a broad "touched surface" suite merely to revalidate already-proven behavior;
* run only unresolved integration-boundary tests that are necessary because multiple story changes interact.

If all affected boundaries were already directly verified and no relevant code changed afterward, no additional story-wide test pass is required.

### Epic verification

The full repository suite is the final regression gate for epic → `main`:

```bash
make check
```

Run it once after the epic implementation and documentation are complete.

If `make check` fails:

1. run only the specific failing checks while fixing them;
2. do not repeatedly rerun the complete suite during debugging;
3. run `make check` once again after all identified failures are fixed.

If `make check` succeeds and no relevant code changes afterward, do not run it again.

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

After a story is implemented and sufficiently verified:

1. merge the story branch into the epic branch;
2. push the epic branch;
3. delete the merged story branch.

Do not perform broader verification merely because a story is about to be committed or merged.

Only run integration tests at the story boundary when the story introduces interactions that were not already verified by focused tests.

### Epic completion

After all epic stories are complete:

1. update tracker/docs;
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

Planning must be proportional to the task.

Do not create large plans for small or obvious changes.

A plan should identify only:

* intended outcome;
* affected components;
* implementation sequence;
* necessary verification.

Do not prescribe a test run after every commit or implementation item.

Instead, define the minimum verification required for each distinct behavior or integration boundary.

Once sufficient context exists, execute rather than continuing to analyze.

Keep `AGENTS.md` consistent with these rules.

---

## v2 implementation

The v2 platform is defined by:

* `docs/architecture/v2_platform_reference.md`
* `docs/v2_platform/progress.md`
* `docs/v2_platform/agent_guide.md`

Before implementing an `E<n>-S<m>` story, read the relevant portion of `agent_guide.md` and the corresponding epic/story information.

Do not reread complete platform documentation when the relevant scope is already known.

For Alpha/Beta/GA wave exits, follow:

`docs/v2_platform/documentation_rebuild.md`

---

## Continuation commands

Resolve terse continuation requests against:

`docs/v2_platform/progress.md`

Treat the tracker as canonical, but verify suspicious or inconsistent status against code before implementing anything.

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

If code already implements a supposedly missing story, update the tracker instead of reimplementing it.

If the tracker says a story is complete but required behavior is demonstrably absent, treat it as a gap and report the inconsistency briefly.

---

## Completion criteria

A task is complete when:

* the requested behavior exists;
* relevant contracts remain valid;
* minimum sufficient verification passes;
* required docs/tracker updates are complete;
* required Git workflow steps for the requested scope are complete.

Once these conditions are proven, stop.

Do not perform additional:

* repository scans;
* test suites;
* verification passes;
* reviews;
* refactors;
* cleanup;
* documentation browsing;

unless a concrete unresolved risk requires them.

Final reports should be concise and contain only:

* what changed;
* verification performed;
* important unresolved issues, if any.

Do not repeat information already obvious from the diff or command output.
