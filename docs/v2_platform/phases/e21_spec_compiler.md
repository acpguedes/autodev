# E21 — Spec Compiler: Scoping, Decomposition & Traceability

**Wave:** v2.1 — Spec & Harness (second epic of the wave; strictly after E20-S1/S2).
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E20 (spec artifacts/registry), E3 (Flow Engine), E5
(Router/Selector), E16-S2 (plan approval state machine)
**Enables:** E22 (verification runs against compiled tasks), E23 (harness runs
compiled flows), E24-S3 (task board renders the dependency graph)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §22.4,
§18.7.13; RFC-007

## Objective

Provide a governed, inspectable path from intent to executable work: a project
intake/scoping stage (greenfield vs. brownfield, with an explicit pre-spec
prototype escape hatch), a Spec Compiler that decomposes approved requirements
into design and then into a task dependency graph scheduled in waves, compilation
of tasks into executable `flow.yaml` runs (the Flow Engine is reused untouched),
and a persisted traceability graph linking requirement ↔ task ↔ run ↔ patch ↔
test ↔ eval.

## Key result

From an approved spec, the platform produces a reviewable task graph (each task
carrying its source requirement IDs), schedules independent tasks concurrently
within sequential waves, executes them as ordinary Flow Engine runs, and can
answer — via API — "which runs/patches/tests implement requirement R-12?" and
"which requirements does this patch touch?".

## Prior art (condensed)

Kiro (requirements → design → tasks with approval gates; dependency graph +
waves), Spec Kit (`/plan` multi-variant, `/tasks` decomposition), Nearform
failure modes ("SDD is execution, not discovery" → the pre-spec prototype
stage). Full comparison and sources in RFC-007.

## Stories

### E21-S1 — Project intake & scoping artifact

Subtasks:
- `E21-S1-T1`: scoping artifact — project kind (greenfield/brownfield), goals, constraints, repo inventory summary (brownfield reuses E7 indexing), explicit out-of-scope list.
- `E21-S1-T2`: pre-spec prototype stage — an optional, time-boxed exploratory run whose output feeds the scoping artifact instead of a spec (prevents "defining specs too early").
- `E21-S1-T3`: intake gate — a spec draft can only enter `under_review` when linked to an approved scoping artifact (waivable per-project for small changes).

| Criterion | Detail |
| --- | --- |
| Functional | A brownfield intake attaches a repo inventory produced from the E7 index; a spec submitted without scoping (and without waiver) is rejected with an actionable message |
| Non-functional | Scoping is data, not prose-only: machine-readable fields for kind, constraints, and scope boundaries |
| DoR (specific) | E20-S2 lifecycle available |
| DoD (specific) | Intake-gate tests; `docs/specs/scoping.md` |
| Dependencies | E20-S2, E7 (brownfield inventory) |

### E21-S2 — Spec Compiler: requirements → design → tasks

Subtasks:
- `E21-S2-T1`: compiler service — for an approved spec, produce a design proposal and a task list where every task declares the requirement IDs it implements; both are artifacts requiring approval (E16-S2 state-machine pattern) before execution.
- `E21-S2-T2`: task dependency graph — explicit `dependsOn` between tasks, cycle detection, and wave computation (waves sequential, tasks within a wave independent).
- `E21-S2-T3`: multi-variant support — the compiler can produce N design/task variants for comparison before approval.

| Criterion | Detail |
| --- | --- |
| Functional | Every generated task references ≥ 1 requirement ID; an unreferenced requirement is reported as uncovered at compile time; the wave schedule respects the dependency graph (verified by property test) |
| Non-functional | Compilation is itself a traced agent run (inspectable, replayable); rejected compilations are stored, not discarded |
| DoR (specific) | E20 spec contract stable; epic ADR for the task/dependency contract filed |
| DoD (specific) | Coverage/cycle/wave tests; `docs/specs/compiler.md` |
| Dependencies | E20-S2, E16-S2 pattern, E2 (planner agents) |

### E21-S3 — Task-to-flow compilation & agent binding

Subtasks:
- `E21-S3-T1`: compile an approved task graph into `flow.yaml` runs — one flow per wave or per task (policy-configurable), using existing node types only (agent/skill/human/subflow/map); the Flow Engine is not modified.
- `E21-S3-T2`: per-task agent/skill binding through the E5 Router/Selector (capability match from the task's requirement text + declared capabilities), with the decision traced.
- `E21-S3-T3`: run linkage — every started run carries `spec_id`/`task_id` correlation so traceability (S4) is populated automatically.

| Criterion | Detail |
| --- | --- |
| Functional | An approved task graph executes end to end as ordinary Flow Engine runs; the selected agent per task is recorded with the selector's reasoning; generated flows validate against `flow.schema.json` |
| Non-functional | Generated flows are deterministic for a frozen task graph (same input → same YAML); budgets propagate per ADR-006 |
| DoR (specific) | E21-S2 available; E5 selector reviewed for task-shaped requests |
| DoD (specific) | End-to-end compile-and-run test on the reference agent; `docs/specs/execution.md` |
| Dependencies | E21-S2, E3, E5 |

### E21-S4 — Traceability graph & queries

Subtasks:
- `E21-S4-T1`: traceability persistence — tenant-scoped edges requirement↔task, task↔run, run↔patch, requirement↔test, requirement↔eval-result in the State Store (dual-backend).
- `E21-S4-T2`: coverage and impact queries — uncovered requirements, orphan tasks/patches (no requirement), full chain for a requirement, requirements touched by a patch.
- `E21-S4-T3`: `GET /v2/specs/{id}/trace` (+ per-requirement drill-down) following §14.1 conventions.

| Criterion | Detail |
| --- | --- |
| Functional | For a completed run the chain requirement→task→run→patch is queryable in both directions; an orphan patch (no requirement link) is reported by the coverage query |
| Non-functional | Trace queries p95 < 300 ms on a 1,000-requirement project; edges append-only (history preserved) |
| DoR (specific) | E21-S3 correlation fields defined |
| DoD (specific) | Bidirectional query tests; API contract tests; `docs/specs/traceability.md` |
| Dependencies | E21-S3, E8-S1 |

## v1/v2 precursor / starting point

- `autodev/agent-planner` and the E16-S2 plan/step approval machinery are the
  closest analogues, but a "plan" today is an execution task list with no
  requirement linkage, no dependency graph, no waves, and no traceability.
  E21 does not replace them: the compiler *emits* plans/flows those mechanisms
  already know how to approve and execute.
- The Flow Engine (E3) and Router/Selector (E5) are consumed as-is; the only
  new persistent surface is the task/traceability model.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD plus story-specific DoD above.
- [ ] Contract tests green for the task-graph contract, generated flows, and
      trace queries.
- [ ] Epic ADR (task & traceability contracts) filed before E21-S2
      implementation starts.
- [ ] `docs/v2_platform/progress.md` updated.
