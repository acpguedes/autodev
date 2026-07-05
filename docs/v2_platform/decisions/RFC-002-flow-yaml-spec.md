# RFC-002: Flow Manifest Specification (`flow.yaml`)

- **Status:** Accepted
- **Author(s):** AutoDev maintainers (via Claude Code)          **Date:** 2026-07-05
- **Reviewers:** repository maintainer
- **Epic(s):** E3                 **Stories:** E3-S1
- **Comment deadline:** 2026-07-05

## Summary

Introduce `flow.yaml`, the declarative, versioned graph contract executed by the
Orchestration Engine: seven canonical node types (agent, skill, tool,
conditional, human, subflow, map), optionally guarded edges (`when` predicates,
`on` signals), triggers, typed IO, retry/timeout defaults, and fail-closed run
budgets.

## Motivation

E3's key result requires "flow-as-configuration": today the only orchestration
is the v1 hardcoded LangGraph pipeline in `backend/orchestrator/service.py`
(plus opt-in dynamic routing), with no declarative definition, no versioning,
and no way for plugins to ship flows. A stable manifest contract is the
foundation every other E3 story (executor, checkpointing, human-in-the-loop,
composite nodes) builds on. Serves guiding principles §2.2 (flow-as-config),
§2.5 (fail closed), and §2.13 (API-first: flows become API-managed artifacts).

## Proposed design

See `docs/flows/spec.md` for the full normative text. Highlights:

- **Document:** `schemaVersion: "1"`, `id` (`namespace/name`), SemVer
  `version`, `hostApi` range, `triggers` (message/webhook/cron/event),
  `input`/`output` JSON Schemas, `defaults` (retries/timeout), `nodes`,
  `edges`, `budgets` (safe defaults, fail closed).
- **Nodes:** canonical vocabulary from reference doc §3; `ref` =
  `namespace/name[@version-or-range]` resolved against registries.
- **Edges:** unconditional, `when` (safe expression over run state), or `on`
  (signal vocabulary, initially `timeout` from human nodes).
- **Graph rules:** single entry, >= 1 terminal, full reachability, no
  unconditional cycles, guard rules per node type, compile-time checking of
  every expression and state reference.
- **Expressions:** minimal safe language (paths, literals, comparisons,
  boolean ops) — no eval, no calls, no arithmetic.

### Contracts and compatibility

- **API change:** none in this story; `/v2/flows` arrives with E3-S2.
- **hostApi/SemVer change:** new artifact type; SDK contract surface bumps
  MINOR (1.0.0 → 1.1.0) by exporting `FlowManifest`.
- **Data migrations:** none (no persistence in this story).

## Alternatives considered

1. **Adopt LangGraph's Python graph API as the contract** — rejected: code,
   not configuration; not versionable/publishable as a manifest; couples
   plugin authors to a library instead of a schema.
2. **Full JSON-Schema-only validation (no typed model)** — rejected: graph
   rules (cycles, reachability, guard consistency) are not expressible in
   JSON Schema; the published schema remains as the interoperable contract,
   with the typed validator as the source of truth.
3. **Jinja2 for predicates/bindings** — rejected: far larger attack surface
   (filters, attribute access) for no needed power; a closed expression
   grammar keeps predicates auditable and replayable.

## Impact

- **Security / RBAC / permissions:** expressions are side-effect-free by
  construction; no manifest field grants permissions (least privilege comes
  from the referenced artifacts' own manifests).
- **Observability:** none yet; events/traces arrive with E3-S2.
- **Cost / budgets / quotas:** budgets always resolve (defaults) and fail
  closed at execution time.
- **Performance / SLOs:** validation of the worked example measures well under
  the 100 ms NFR (contract-tested).

## Implementation and rollout plan

E3-S1 (this RFC): parser/validator + published schema + SDK export + docs.
E3-S2: registry, durable execution, `/v2/flows`. E3-S3/S4/S5: checkpointing,
human nodes, composite nodes — all consuming this contract unchanged.

## Open questions

- Trigger payload shape standardization is deferred to E3-S2/E9 (Event Bus).
- Additional `on` signals (e.g. `error`) may extend the vocabulary in a MINOR
  schema revision.
