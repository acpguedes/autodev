# v2 Platform — Refactor Tracking

This directory tracks the implementation of the AutoDev Architect **v2.0** platform
refactor: a complete architecture inversion from a fixed linear agent pipeline into a
small, stable core surrounded by typed **extension points** (plugins, agents, flows,
reasoning strategies, routing/selection, skills, context providers, UI panels), all
declarative, versioned, and OSS-first.

## Canonical source

**`docs/architecture/v2_platform_reference.md`** is the single source of truth for the
v2.0 design: vision, guiding principles, glossary, every subsystem's architecture and
contracts, non-functional requirements, the full delivery roadmap (epics E0-E17 with
stories, subtasks, and acceptance criteria), governance/versioning rules, KPIs, and
ready-to-copy templates (plugin/agent/flow/skill/eval manifests, ADR, RFC, DoR, DoD,
story). It is ~6,600 lines across 21 sections — this directory exists so that day-to-day
implementation work doesn't require re-reading all of it every time.

If anything in this directory ever disagrees with the reference document, **the
reference document wins** — these are a navigable summary and execution layer on top
of it, not a replacement.

> Note on language: the reference document is written in pt-BR (its declared scope).
> The files in this directory are written in English for consistency with the rest of
> `docs/` and with `AGENTS.md`/`CLAUDE.md`, which is what most contributing agents read
> first. Epic/story identifiers, manifest field names, and event names are unchanged
> either way — those are part of the actual contracts, not prose.

## How this differs from the existing `docs/roadmap.md` / `mvp_refactor_plan.md`

`docs/roadmap.md` and `docs/implementation/mvp_refactor_plan.md` track **incremental,
additive** work on the current (v1) architecture — hardening the existing linear
pipeline, filling in stubs, rebuilding the frontend on Tailwind/shadcn, etc. Several of
those units are useful precursors to v2 epics (each `phases/E<n>_*.md` file notes the
relevant ones), but the v2.0 platform described here is a distinct, larger initiative:
it replaces the pipeline itself with a plugin/flow architecture, not just hardens it.
`docs/v2_platform/documentation_rebuild.md` explains how the two roadmaps get
reconciled as v2 epics land.

## Contents

| File / directory | Purpose |
| --- | --- |
| [`progress.md`](progress.md) | Living tracker: which epic/story is Done/In progress/Not started, current wave (Alpha/Beta/GA), wave exit-gate checklists, changelog. **Start here** to see where the rewrite stands. |
| [`agent_guide.md`](agent_guide.md) | How to pick up an epic/story: workflow gates (G1-G5), DoR/DoD, ADR/RFC triggers, naming/versioning conventions, and how to keep the tracking docs in sync. **Read this before starting implementation work.** |
| [`documentation_rebuild.md`](documentation_rebuild.md) | Playbook for rebuilding the rest of the project's documentation (root README, `docs/architecture/*`, `docs/implementation/*`, etc.) as v2 epics and waves land, since this is a full architecture refactor and the old docs will otherwise drift out of sync with the new one. |
| [`phases/`](phases/) | One file per epic (`E0` through `E17`): objective, key result, every story with its subtasks and functional/non-functional/DoR/DoD criteria, dependencies, wave assignment, and what existing v1 code (if any) is a starting point. |
| [`templates/`](templates/) | Copy-ready templates: `story_template.md`, `adr_template.md`, `rfc_template.md`, `dor_checklist.md`, `dod_checklist.md`, and worked manifest examples under `templates/manifests/` (`plugin.yaml`, `agent.yaml`, `flow.yaml`, `skill.yaml`, `eval.yaml`). |
| [`decisions/`](decisions/) | ADR/RFC log for architecturally significant decisions made during the rewrite, with an index and the process for adding new entries. |

## Quick start for a new contributor or agent

1. Read `progress.md` to see the current wave and epic statuses.
2. Pick up (or get assigned) an epic; read its `phases/E<n>_*.md` file.
3. Read `agent_guide.md` for the workflow gates, DoR/DoD, and conventions.
4. Do the work; use `templates/` for new stories, manifests, ADRs, or RFCs as needed.
5. Update `progress.md` and the epic's phase doc when a story/epic changes state.
6. At a wave boundary, follow `documentation_rebuild.md` to bring the rest of the
   docs tree up to date.
