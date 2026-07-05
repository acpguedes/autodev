# ADR-004: Flow Manifest and Node-Type Vocabulary

- **Status:** Accepted
- **Date:** 2026-07-05
- **Authors:** AutoDev maintainers (via Claude Code)
- **Related epic:** E3 (story E3-S1)
- **Supersedes/Relates to:** RFC-002 (proposal); ADR-002 (plugin manifest),
  ADR-003 (agent manifest) — same manifest family and conventions.

## Context

E3 needs a declarative flow contract before any execution work. The v1
orchestrator is hardcoded; plugins and operators need a versionable,
publishable artifact that the Orchestration Engine, the visual editor (E3-S6),
and the Control Plane API can all share. The contract must be validatable
fast (< 100 ms), safe (no code execution from manifests), and consistent with
the plugin/agent manifest conventions already shipped by E1/E2.

## Decision

1. **`flow.yaml` schemaVersion `"1"`** with `id` (`namespace/name` kebab-case),
   SemVer `version`, and `hostApi` range — same conventions as `plugin.yaml` /
   `agent.yaml` (reference doc §3.2).
2. **Node-type vocabulary fixed to the canonical seven** from reference doc §3:
   `agent`, `skill`, `tool`, `conditional`, `human`, `subflow`, `map`.
3. **Guarded-edge semantics:** edges are unconditional, `when`-guarded
   (predicate over run state), or `on`-guarded (signal; initially `timeout`).
   Conditional routing lives on edges, not inside nodes.
4. **Graph structural rules:** single entry node, >= 1 terminal, full
   reachability, and **no unconditional cycles** (loops must contain a guarded
   edge). Implicit parallel fan-out is rejected — parallelism is explicit via
   `map` (E3-S5).
5. **Safe expression language:** a closed grammar (paths, literals,
   comparisons, boolean operators) implemented in
   `backend/flows/expressions.py`; state roots restricted to `flow.input`,
   `nodes.<id>.output`, and `item` (map bindings).
6. **Fail-closed budgets by default:** omitted `budgets` resolve to
   10 USD / 3600 s / 2M tokens; the engine stops runs that exceed them.
7. **Published contract:** JSON Schema at
   `backend/flows/schemas/flow.schema.json`; typed validator is authoritative;
   `FlowManifest` exported via the SDK (contract 1.0.0 → 1.1.0, MINOR).

## Alternatives considered

1. **LangGraph graphs as the contract** — code not config; rejected (RFC-002).
2. **Open node-type vocabulary (plugins add node types in schemaVersion 1)** —
   rejected for now: extension-point work belongs to the plugin catalog and
   would fragment editor/engine support; revisit post-Alpha with a dedicated
   RFC.
3. **Allowing unconditional cycles with a max-iterations runtime cap** —
   rejected: pushes a static modeling error to runtime failure; guarded loops
   express rework legitimately.

## Consequences

- **Positive:** every E3 story now codes against one stable contract; plugins
  can ship flows the same way they ship agents; the editor can validate
  client-side from the published JSON schema.
- **Negative / trade-offs:** the expression language is intentionally weak
  (no arithmetic/functions); complex routing logic must live in a
  `skill`/`tool` node that computes state for a predicate to test.
- **Contract impact:** new artifact type (flow, SemVer'd); SDK MINOR bump;
  no migrations.

## Rollback plan

Nothing persists in this story; rolling back is deleting `backend/flows/` and
the SDK export (revert to SDK contract 1.0.0). Once E3-S2 persists flow
definitions, changes to the manifest format require a new schemaVersion and a
superseding ADR.

## References

- RFC-002; `docs/flows/spec.md`;
  `docs/architecture/v2_platform_reference.md` §3, §18.6, Appendix (C).
