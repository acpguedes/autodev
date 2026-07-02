# Documentation Rebuild Playbook

## Why this document exists

The v2.0 rewrite described in `docs/architecture/v2_platform_reference.md` is not an
incremental feature — it is an **architecture inversion**: the v1 fixed linear agent
pipeline (Navigator -> Analyzer -> Architect -> Coder -> DevOps -> Validator ->
Responder) becomes a small core with everything (agents, flows, reasoning, routing,
skills, context/RAG, even UI panels) exposed as typed **extension points** inhabited
by versioned **plugins**. Most of the current documentation tree describes the v1
model, or an intermediate "target architecture" written before the v2 plugin/agent
framework vision existed. Left alone, that documentation will silently drift out of
sync with the code as v2 epics land — a problem this project has already hit once
(`docs/implementation/mvp_refactor_plan.md`'s evaluation section flagged "Docs
overclaim vs. flag-gated reality" as a concrete, named issue).

This playbook exists so that documentation is rebuilt **deliberately, at defined
checkpoints**, instead of drifting or being patched ad hoc. It complements, and does
not replace, the per-story documentation requirement already in the global DoD
(`docs/v2_platform/templates/dod_checklist.md`: "Documentation updated in `docs/` and
the project root"). That per-story rule keeps docs from lying about what shipped;
this playbook is the periodic holistic pass that keeps the *shape* of the docs tree
coherent as whole epics and waves land.

## Source-of-truth hierarchy (do not violate)

1. **`docs/architecture/v2_platform_reference.md`** — canonical design authority for
   the v2.0 platform (vision, principles, every subsystem contract, the full E0-E13
   roadmap, governance, KPIs, templates). This document does not get "rebuilt" by this
   playbook — it evolves through its own governance process (§19.7 of that document:
   owned by Core/Steering, reviewed every MINOR, revalidated every MAJOR, changed via
   RFC/ADR). Treat it as authoritative until GA, at which point step 7 below retires
   its role in favor of a permanent, split docs set.
2. **`docs/v2_platform/`** (this directory) — execution tracking: what has actually
   landed (`progress.md`, `phases/E<n>_*.md`), decisions made (`decisions/`), and how
   to work (`agent_guide.md`, `templates/`). Updated continuously, per story.
3. **Everything else under `docs/` and the repo root** — the *stable, product-facing*
   documentation tree. This is what this playbook rebuilds, and it should always
   describe **what the running code actually does today**, never the v2 aspiration
   ahead of implementation. `docs/feature_matrix.md`'s `default`/`optional`/`stub`/
   `planned` status key is the model to keep following: state reality precisely,
   don't round up.

## When to run a rebuild pass

Run this playbook at each **wave gate** defined in
`docs/architecture/v2_platform_reference.md` §18.9 and mirrored in
`docs/v2_platform/progress.md` — **Alpha exit, Beta exit, GA exit** — not after every
individual story. Story-level doc updates are handled by the DoD already. Running a
full pass more often produces churn without benefit; running it less often lets the
gap between docs and code reopen.

Also run it (out of band, for the specific affected files) whenever an accepted
RFC/ADR changes something a root-level doc claims — e.g. a stack decision recorded in
`docs/architecture/stack_decisions.md`.

## Inventory: every doc file, its disposition, and its trigger

| File | Current role | Disposition as v2 lands | Trigger / owning epic |
| --- | --- | --- | --- |
| `README.md` | Top-level pitch, quickstart, feature overview | Update summary at each wave exit; full rewrite at GA to describe the plugin/agent-framework platform, not the v1 pipeline | Alpha/Beta/GA exits |
| `DESCRIPTION.md` | Longer project description (positioning) | Keep in lockstep with `README.md`; rewrite at GA | GA exit |
| `AGENTS.md`, `AGENT.md`, `CLAUDE.md` | Operating guides for coding agents | Add a pointer to `docs/v2_platform/agent_guide.md` once E1 lands (this already happened — see step 8 below); revisit stack-direction sections as E0/E1 land | E0, E1 |
| `docs/product/project_charter.md` | Vision, personas, success metrics | Reconcile with reference doc §1 (personas, objectives) once Alpha exits; this is the "why", keep it short and let `v2_platform_reference.md` carry the detail | Alpha exit |
| `docs/roadmap.md` | Release-by-release goals and status ("Delivered" section, Release 0.1-1.0) | Mark units superseded by epic work; once an epic supersedes a "Release 0.x" goal, annotate the release entry pointing at `docs/v2_platform/progress.md` instead of maintaining two parallel roadmaps | Each wave exit |
| `docs/implementation/mvp_refactor_plan.md` | Pre-v2 incremental backlog (Units 1-30, Phases 1-5) | Freeze as historical once its remaining open units are superseded by the corresponding epic (e.g. Unit 25's tool-use loop -> E4; Units 11-19 frontend rebuild -> E10); add a banner noting supersession, do not delete | As each epic subsumes its units |
| `docs/feature_matrix.md` | Per-feature `default`/`optional`/`stub`/`planned` status | Update every row whose backing epic has landed; add new rows for v2-only capabilities (plugin manifests, contract tests, RBAC, etc.) | Every wave exit |
| `docs/architecture/initial_architecture.md` | Historical MVP decisions (already marked historical) | No action beyond keeping the "historical note" banner accurate | — |
| `docs/architecture/target_architecture.md` | Pre-v2 "target production architecture" (Postgres/Redis/MinIO/LangGraph, still linear-pipeline shaped) | This describes an **earlier, superseded** target than the v2 plugin architecture. Retire it incrementally: as each relevant epic (E0, E8, E3) lands, fold its accurate content into the new architecture doc (step 7) and shrink this file to a historical pointer | E0, E3, E8 |
| `docs/architecture/stack_decisions.md` | Pre-v2 recommended stack | Reconcile against `docs/architecture/v2_platform_reference.md` §"Preferred decisions" / stack table; once E0 lands (Postgres/Redis/MinIO wired), retire the "planned" framing | E0 |
| `docs/architecture/weaknesses_and_strategies.md` | Honest debt log (weaknesses 1-11) | Check off each weakness as its remediation epic lands; keep it honest — don't close an item until the epic's DoD is actually met | Continuous, per epic |
| `docs/architecture/plugin_seams.md` | Documents the v1 auto-discovery seams (routers/agents/CLI) | Superseded by E1's Plugin Host + `plugin.yaml`. Once E1 lands, rewrite this file to document the real Plugin Host (or fold it into the new `docs/plugins/` set from step 7) and mark the old seam mechanism historical | E1 |
| `docs/implementation/agent_spec.md` | v1 agent behavior/output spec | Superseded by E2's `agent.yaml` contract + Agent Runtime. Rewrite once E2 lands; until then it documents real, current behavior and should not be deleted | E2 |
| `docs/implementation/dynamic_orchestration.md` | Specialized agents + optional dynamic routing/`SupervisorPolicy` | Superseded by E3 (flow engine) and E5 (Router & Selector). Rewrite once those land; content becomes historical precedent notes | E3, E5 |
| `docs/implementation/skills_subsystem.md` | v1 skills registry + built-ins | Superseded by E6's `skill.yaml` + Skill Registry. Rewrite once E6 lands | E6 |
| `docs/implementation/patches_and_validation.md` | Patch engine, sandbox, jobs, observability, repo intelligence (flag-gated) | Split across E3 (flow nodes that apply patches), E7 (repo intelligence -> Context/RAG), E11 (sandbox hardening), E12 (validation gates). Rewrite per landing epic rather than all at once | E3, E7, E11, E12 |
| `docs/implementation/data_model.md` | Recommended persistence model | Superseded by E8's multi-tenant model + migrations. Rewrite once E8 lands | E8 |
| `docs/implementation/implementation_strategy.md` | General implementation path (prototype -> robust platform) | Superseded in spirit by `docs/v2_platform/progress.md` + the epic phase docs. Retire to a historical pointer once Alpha exits | Alpha exit |
| `docs/implementation/self_hosting_oss.md` | Self-hosting guide | Update as E0 (Postgres/Redis/MinIO default path) and E13 (Marketplace, plugin install) land | E0, E13 |
| `docs/security.md` | Current security posture, env flags | Update as E0-S4 (secrets/CVE baseline), E1-S3 (plugin isolation), E11 (RBAC, sandbox hardening), E13-S3 (package signing) land | E0, E1, E11, E13 |
| `docs/testing.md` | Local dev/test/lint/build guide | Update as E12 introduces contract tests, coverage gates, and evals into the standard workflow | E12 |
| `docs/workflows/` (currently empty) | Reserved | Natural home for real `flow.yaml` examples once E3 lands | E3 |

## Step-by-step procedure (run at each wave exit)

1. **Freeze scope.** Confirm in `docs/v2_platform/progress.md` which wave just
   exited and which epics/stories are actually Done (not just started). Only rebuild
   docs for what is actually shipped and DoD-complete.
2. **Update the architecture narrative.** Fold newly-landed epic content into
   `docs/architecture/target_architecture.md` (or its successor — see step 7 at GA),
   replacing pipeline-era descriptions with the plugin/flow model. Update
   `docs/architecture/stack_decisions.md` and `docs/architecture/plugin_seams.md`
   accordingly.
3. **Update status trackers.** Refresh every row in `docs/feature_matrix.md` whose
   epic landed; update `docs/roadmap.md` to point superseded "Release 0.x" goals at
   the corresponding epic in `docs/v2_platform/progress.md`.
4. **Update subsystem docs.** For each landed epic, rewrite its
   `docs/implementation/*.md` counterpart per the inventory table above.
5. **Update product framing.** Revisit `docs/product/project_charter.md` if the
   vision, personas, or success metrics shifted; keep it a short pointer into
   `v2_platform_reference.md` §1 rather than duplicating it.
6. **Update root-level docs.** Refresh `README.md`, `DESCRIPTION.md`, `AGENTS.md`,
   `AGENT.md`, `CLAUDE.md`, `docs/security.md`, and `docs/testing.md` for anything
   the wave changed (stack, setup steps, security posture, test/CI workflow).
7. **At GA only — split the reference document.** Once E13 lands and the GA
   checklist (`phases/e13_marketplace_ga.md`) is signed off, the reference document's
   job (guiding a build that hasn't happened yet) is complete. Split its stable
   content into permanent, section-sized docs that are easier to maintain than one
   6600-line file, for example:
   - §4 (architecture) -> `docs/architecture/target_architecture.md` (rewritten)
   - §5 (plugins) -> `docs/plugins/manifest.md`, `docs/plugins/permissions.md`
   - §6 (agents) -> `docs/agents/manifest.md`, `docs/agents/runtime.md`
   - §7 (flows) -> `docs/flows/spec.md`
   - §8 (reasoning) -> `docs/reasoning/contract.md`, `docs/reasoning/policies.md`
   - §9 (routing/selection/eval) -> `docs/routing/`, `docs/evals/spec.md`
   - §10 (skills) -> `docs/skills/manifest.md`
   - §11 (context/RAG) -> `docs/context_rag.md`
   - §12-13 (patches, persistence) -> `docs/implementation/patches_and_validation.md`,
     `docs/implementation/data_model.md` (rewritten)
   - §14 (APIs/events/MCP) -> `docs/api/v2.md`
   - §15 (UI/UX) -> `docs/design_system.md`
   - §16-17 (NFRs, quality) -> `docs/security.md`, `docs/testing.md` (rewritten)
   - §19-20 (governance, KPIs) -> `docs/governance.md`, `docs/kpis.md`
   - §21 (templates) -> already living in `docs/v2_platform/templates/`; keep them
     there permanently rather than re-duplicating.

   Archive `docs/architecture/v2_platform_reference.md` itself (rename with a
   `-archived` suffix or add a banner) rather than deleting it — it remains the
   historical record of the design decisions behind v2.0. Decide at that point
   whether `docs/v2_platform/` becomes a permanent historical record (recommended:
   keep `progress.md` and `decisions/` indefinitely as the project's decision and
   audit trail) or whether its active-tracking role is retired in favor of whatever
   process governs v3.
8. **Consistency check.** Confirm no root or `docs/` file overclaims relative to
   `docs/feature_matrix.md`; confirm every internal cross-link (like the ones in this
   file) still resolves; confirm `docs/v2_platform/progress.md`'s Changelog has an
   entry for the rebuild pass itself.

## Rules that apply throughout, not just at wave gates

- **Never let `README.md`/`DESCRIPTION.md` claim a capability that
  `docs/feature_matrix.md` lists as `stub` or `planned`.** This exact failure mode is
  called out in `docs/implementation/mvp_refactor_plan.md`'s evaluation and must not
  recur during the v2 rewrite.
- **Don't delete historical docs — mark them superseded.** Add a banner (see the
  existing pattern in `docs/architecture/initial_architecture.md`,
  `docs/architecture/target_architecture.md`, and
  `docs/architecture/stack_decisions.md`, which already use dated "Current status"
  callouts) pointing at the doc that replaced it.
- **One rebuild pass per wave exit, tracked as its own changelog entry** in
  `docs/v2_platform/progress.md`, so it's visible that the pass happened and when.
