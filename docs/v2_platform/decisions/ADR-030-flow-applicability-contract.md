# ADR-030: Flow Applicability Contract and Deterministic Selection Gate

- **Status:** Accepted
- **Date:** 2026-10-04
- **Authors:** AutoDev platform team
- **Related epic:** E63
- **Relates to:** RFC-002 (flow.yaml spec), ADR-004 (flow manifest and node
  types), ADR-029 (project scope)

## Context

Flows existed with no way to say *when* they apply, and the chat path ignored
them: every turn ran the same seven-agent pipeline, `architect` included.
Selecting a flow with a model alone would reintroduce the defect one layer up
(a bootstrap flow chosen in a populated project).

## Decision

1. **Additive manifest fields** (`schemaVersion` stays `"1"`; a MINOR change to
   the public flow-manifest contract, §19.1/§19.3): `purpose`, `whenToUse`,
   `whenNotToUse` (text) and `requires` (structured preconditions `populated`,
   `git`, `tests`, `languages` over `backend.projects.state.ProjectState`). A
   flow declaring neither `purpose` nor `whenToUse` is never auto-selected but
   stays explicitly runnable.
2. **The deterministic gate — not the model — enforces applicability.** The
   selector first eliminates every flow whose `requires` conflicts with the
   probed project state; only survivors' metadata reach the model, which may
   answer `none`. Any error, timeout or unparseable answer fails closed to
   "no flow" (direct execution), never to a structuring flow.
3. **`_infer_run_type` is replaced, not extended**: whole-word intent grounded
   in the project state. `RunTypeRouter` moves from standalone to the default
   per-run agent-order policy; an existing-repo change skips `architect`
   unless the intent is architectural. A non-default `OrchestratorConfig.agent_order`
   still wins. `AUTODEV_DYNAMIC_ORCH` is redundant for `/chat` (the
   `/chat/dynamic` endpoint is unchanged; its removal is a separate deprecation).
4. Every decision is recorded as `flow.selection.matched` /
   `flow.selection.skipped`, carrying candidates, gate eliminations and reason.

## Consequences

- Selection sends only flow metadata and task text to a provider — never file
  contents, secrets or the root path.
- Rollback is reverting the chat wiring; fields, probe and selector are inert
  without it.
