# Agent Guide — Working on the v2 Platform Refactor

This guide is for any coding agent (Claude Code, Codex, or a human contributor)
picking up work on the AutoDev Architect v2.0 rewrite. Read it before starting an
`E<n>-S<m>` story. It complements, and does not replace, `CLAUDE.md` and `AGENTS.md`
at the repo root — those govern the whole repository (execution environment,
stack preferences, general working style); this guide is specific to the v2 platform
epics tracked under `docs/v2_platform/`.

## 1. Orient yourself before writing code

1. Read `docs/v2_platform/progress.md` to see the current wave and which epics/stories
   are already Done, In progress, or Not started.
2. Read the relevant `docs/v2_platform/phases/E<n>_*.md` file for the epic you're
   picking up. It has the objective, key result, every story's subtasks and
   CF/CNF/DoR/DoD table, dependencies, and a "v1 precursor" section pointing at any
   existing code that's a starting point (or that needs to be replaced).
3. For the full, authoritative wording of a story's criteria — or anything this
   summary layer omits — go to the canonical source:
   `docs/architecture/v2_platform_reference.md`, the section cited at the top of the
   phase doc (e.g. §18.6 for E0-E6, §18.7 for E7-E13, §18.8 for epic dependencies,
   §18.9 for wave gates). **The reference doc, not the phase doc, is the source of
   truth if the two ever disagree** — the phase docs are a navigable summary, and
   should be corrected to match the reference doc rather than the other way around.
4. Check `docs/v2_platform/decisions/README.md` for any ADR/RFC already covering the
   area you're about to touch.

## 2. Follow the workflow gates (§18.1)

Every story moves through: `Backlog -> Ready -> In Progress -> In Review -> Validation
-> Done`, gated by G1-G5:

| Gate | Transition | What must be true |
| --- | --- | --- |
| G1 | Backlog -> Ready | Global DoR + story-specific DoR satisfied; dependencies resolved or mockable |
| G2 | Ready -> In Progress | Owner assigned; branch/worktree created |
| G3 | In Progress -> In Review | Patch dry-runs cleanly in a guarded path; local tests green; self-reviewed; no secrets in the diff |
| G4 | In Review -> Validation | >= 1 human approval; contract tests for touched extension points green; ADR/RFC referenced if there's an architectural decision |
| G5 | Validation -> Done | Validation Gate green (lint + tests + coverage + security); no SLO regression; global + story-specific DoD complete |

Use `docs/v2_platform/templates/dor_checklist.md` before starting a story and
`docs/v2_platform/templates/dod_checklist.md` before marking it Done. Use
`docs/v2_platform/templates/story_template.md` when writing up a new story or
subtask (YAML form for structured backlog data, Markdown form for the human-facing
ticket/PR description).

## 3. When you need an ADR or RFC

Per §19.3 of the reference doc: any change that would cause a **MAJOR** version bump
of a platform artifact (core, plugin, agent, skill, flow, eval, API, or event — see the
SemVer table in §19.1) requires an accepted RFC *before* implementation and a
corresponding ADR once the decision is fixed. A **MINOR** change to a public contract
still warrants a lightweight ADR. Use `docs/v2_platform/templates/rfc_template.md` and
`docs/v2_platform/templates/adr_template.md`, and file the result under
`docs/v2_platform/decisions/`, updating that directory's index table.

## 4. Naming, versioning, and contract conventions (cheat sheet)

- **IDs:** `namespace/name` in kebab-case for every plugin, agent, skill, and flow
  (e.g. `autodev/agent-coder`).
- **Versions:** SemVer `MAJOR.MINOR.PATCH` for every artifact; compatibility ranges use
  `hostApi: ">=2.0 <3.0"` syntax.
- **Events:** `domain.entity.action`, past tense (e.g. `run.step.completed`,
  `plugin.installed`).
- **API:** everything new lives under `/v2`, with a `schemaVersion` on every payload.
- **Manifests:** `plugin.yaml`, `agent.yaml`, `flow.yaml`, `skill.yaml`, `eval.yaml` —
  worked examples for each are in `docs/v2_platform/templates/manifests/`.
- **Least privilege by default:** no permission entry in a manifest means denied. Never
  hardcode a permission grant to make a test pass — declare it.
- **Fail closed:** budgets, permissions, and `hostApi` compatibility all fail closed
  (deny/stop) rather than fail open, per the reference doc's Principle 5 (§2.5) and the
  DoD checklist.

## 5. Use existing code as a starting point, not as the target shape

Several v2 epics have an informal precursor already in the codebase (documented per
epic in each phase doc's "v1 precursor" section, and summarized in
`docs/feature_matrix.md`): auto-discovered plugin seams, the agent/skill registries,
dynamic orchestration behind `AUTODEV_DYNAMIC_ORCH`, the SQLite store abstraction with
migrations, the validation sandbox. These are useful references for behavior parity
(see e.g. E2-S5, "package the existing v1 agent as a plugin ... migrate behavior with
parity") but **do not satisfy the v2 contracts as-is** — no manifest, no `hostApi`
versioning, no declared permissions, no contract tests. Treat them as inputs to
migrate, not as epics you can mark Done because "the feature already exists."

## 6. Keep the tracking docs in sync

After a story or epic changes state:

1. Update the "Status"/"Stories complete" fields at the top of the relevant
   `docs/v2_platform/phases/E<n>_*.md`.
2. Update the epic's row in `docs/v2_platform/progress.md`'s table, and check off any
   wave-gate criteria that are now satisfied.
3. Add a dated line to `progress.md`'s Changelog section.
4. If the change is architecturally significant, make sure the ADR/RFC exists and is
   indexed in `docs/v2_platform/decisions/README.md`.
5. If the change lands at a wave boundary (Alpha/Beta/GA exit), follow
   `docs/v2_platform/documentation_rebuild.md` to update the rest of the docs tree —
   don't let `README.md`, `docs/feature_matrix.md`, or `docs/roadmap.md` drift out of
   sync with what actually shipped.

## 7. Execution environment reminder

E0 and later v2 platform work should prefer the containerized backend runtime introduced
by E0-S0. Run backend tests, CLI commands, migrations, and validation through the
container targets once available, or directly through Docker Compose before E0-S1 lands.
The backend image owns the Python runtime and `.venv`, while SQLite/config state lives
in Docker volumes.

For pre-E0 work or emergency local-only debugging, this repo's `CLAUDE.md`/`AGENTS.md`
still require activating the project virtualenv for Python-related host commands:
`source .venv/bin/activate && <command>` (create it first with
`python -m venv .venv` if missing).
