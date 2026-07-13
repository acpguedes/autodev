# E20 — Spec Core: Constitution, Spec Artifacts & Registry

**Wave:** v2.1 — Spec & Harness (first epic of the wave; S1–S2 can start as soon
as RFC-007 is accepted, without waiting for the v2.0 GA gate, since the layer is
additive and touches no v2.0 exit criterion).
**Status:** Not started · **Stories:** 0/5 complete
**Depends on:** E1 (plugin/extension-point model), E8-S1 (tenant-scoped State
Store), E9 (API/event conventions), E16-S2 (approval state-machine pattern)
**Enables:** E21 (compiler consumes registered specs), E22 (verification links
to requirements), E23 (harness binds a spec), E24-S1/S2 (Spec Studio edits these
artifacts), E25-S2 (extension specs)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §22.1–§22.3,
§18.7.12; RFC-007 (`../decisions/RFC-007-spec-harness-layer.md`)

## Objective

Make specifications first-class, versioned platform objects — a project-wide
**constitution** (durable steering principles) plus per-feature **specs**
(requirements in a constrained, testable grammar; design; task references) —
stored in a tenant-scoped Spec Registry with an immutable-published lifecycle,
a brownfield delta/change-proposal model, a `/v2/specs` API surface, and a
Context Provider that delivers scoped spec bundles to agents instead of
whole-repo dumps.

## Key result

A spec can be authored (`spec.yaml` + constitution), validated against a
published JSON schema, registered, versioned, and queried through `/v2/specs`;
a change proposal against an existing spec applies requirement-scoped deltas
(ADDED/MODIFIED/REMOVED) without conflicting with other in-flight proposals;
and any agent run can receive the "Spine" context bundle for its target spec
through the E7 `ContextComposer`.

## Prior art (condensed)

GitHub Spec Kit (constitution + phase gates), Amazon Kiro (requirements.md in
EARS notation / design.md / tasks.md, steering files), OpenSpec (requirement-
scoped deltas, propose→apply→sync→archive), AGENTS.md/CLAUDE.md convergence
(constitution interop). Full comparison and sources in RFC-007.

## Stories

### E20-S1 — `spec.yaml` contract & constitution model

Subtasks:
- `E20-S1-T1`: typed `spec.yaml` contract — metadata (`id`, SemVer `version`, `hostApi`), `requirements[]` in EARS grammar (`WHEN <condition> THE SYSTEM SHALL <behavior>`, one behavior per clause, stable requirement IDs `R-<n>`), `design` (architecture notes, contract vs. internal-design split), `tasks[]` refs, and `acceptance[]` (Given/When/Then scenarios per requirement).
- `E20-S1-T2`: constitution contract — project-scoped steering principles (imperative rules, stack choices, conventions), size-bounded, versioned separately from feature specs.
- `E20-S1-T3`: published JSON schemas (`spec.schema.json`, `constitution.schema.json`) and SDK contract export (MINOR bump).

| Criterion | Detail |
| --- | --- |
| Functional | A valid `spec.yaml` parses into the typed model; an EARS clause with two behaviors or a requirement without a stable ID fails validation with an actionable message |
| Non-functional | Schema validation < 100 ms per document; contracts are additive to the SDK (no breaking change to existing manifests) |
| DoR (specific) | RFC-007 accepted; EARS grammar subset and requirement-ID scheme fixed in the epic ADR |
| DoD (specific) | Contract tests for valid/invalid documents; `docs/specs/contract.md`; schemas published like `flow.schema.json` |
| Dependencies | E1-S1 (manifest/validator pattern), RFC-007 |

### E20-S2 — Spec Registry & lifecycle

Subtasks:
- `E20-S2-T1`: tenant-scoped persistence of constitutions/specs/requirements in the State Store (new tables, dual-backend SQLite/PostgreSQL, RLS on Postgres per ADR-010 pattern).
- `E20-S2-T2`: lifecycle state machine `draft → under_review → approved → published` (immutable once published; new content = new SemVer version), reusing the E16-S2 approval state-machine pattern.
- `E20-S2-T3`: `spec.*` events (`spec.created`, `spec.submitted`, `spec.approved`, `spec.published`, `spec.deprecated`) added append-only to the event catalog.

| Criterion | Detail |
| --- | --- |
| Functional | Publishing freezes a spec version; editing a published spec creates a new draft version; approval transitions are recorded with actor and are queryable |
| Non-functional | All queries tenant-scoped (negative-case isolation tests); published versions immutable at the storage layer |
| DoR (specific) | E20-S1 contract available; migration plan reviewed |
| DoD (specific) | Lifecycle + tenant-isolation tests; event catalog updated append-only; `docs/specs/registry.md` |
| Dependencies | E20-S1, E8-S1, E9-S3 |

### E20-S3 — Delta / change-proposal model (brownfield)

Subtasks:
- `E20-S3-T1`: change-proposal artifact — intent/scope plus requirement-scoped deltas marked ADDED/MODIFIED/REMOVED against a published spec version.
- `E20-S3-T2`: lifecycle `propose → apply → sync → archive` — `apply` marks the proposal executing, `sync` merges deltas into a new spec version, `archive` preserves the proposal with date prefix.
- `E20-S3-T3`: conflict rule — two in-flight proposals conflict only if they touch the same requirement ID; detection surfaced at propose time.

| Criterion | Detail |
| --- | --- |
| Functional | Two proposals touching different requirements of the same spec proceed in parallel; touching the same requirement flags a conflict at propose time; `sync` produces a new SemVer version whose diff equals the applied deltas |
| Non-functional | Archived proposals immutable; full history reconstructable from proposals alone |
| DoR (specific) | E20-S2 lifecycle available |
| DoD (specific) | Parallel-proposal and conflict tests; `docs/specs/changes.md` |
| Dependencies | E20-S2 |

### E20-S4 — `/v2/specs` API, MCP exposure & constitution interop

Subtasks:
- `E20-S4-T1`: `/v2/specs` + `/v2/specs/{id}` + `/v2/specs/{id}/changes` + constitution endpoints, following §14.1 conventions (schemaVersion envelope, Problem Details, Idempotency-Key), auto-discovered router.
- `E20-S4-T2`: MCP exposure of read/query spec operations (least-privilege mapping like E9-S4).
- `E20-S4-T3`: constitution export bridge — render the active constitution as `AGENTS.md` (and optional `CLAUDE.md`) in the target repo so external agents (Cursor, Claude Code, Codex) natively read the same steering rules.

| Criterion | Detail |
| --- | --- |
| Functional | Full spec lifecycle drivable via `/v2` only (API-first, §2.13); exported `AGENTS.md` round-trips the constitution content and carries a generation stamp |
| Non-functional | Read p95 < 300 ms; no UI/CLI path touches the State Store directly |
| DoR (specific) | E20-S2/S3 available |
| DoD (specific) | Contract tests per endpoint; OpenAPI updated; `docs/specs/api.md` |
| Dependencies | E20-S2, E20-S3, E9-S1, E9-S4 |

### E20-S5 — Spec Context Provider ("the Spine")

Subtasks:
- `E20-S5-T1`: a `ContextProvider` plugin that assembles, for a target spec/task, the scoped bundle: target spec + the public contracts of its declared dependencies (one hop) + relevant constitution slices — never the whole spec corpus.
- `E20-S5-T2`: budget-aware truncation with deterministic priority (constitution > target requirements > dependency contracts).
- `E20-S5-T3`: provider registered through the E7 `ContextComposer` with per-provider timeout/isolation.

| Criterion | Detail |
| --- | --- |
| Functional | An agent run bound to a spec receives the Spine bundle in context; dependency contracts beyond one hop are excluded; bundle content is reproducible for a frozen spec version |
| Non-functional | Bundle assembly < 200 ms for a 100-spec project; respects the composer's context budget |
| DoR (specific) | E20-S2 registry queryable; E7-S4 provider contract reviewed |
| DoD (specific) | Provider contract test; determinism test; `docs/specs/context.md` |
| Dependencies | E20-S2, E7-S4 |

## v1/v2 precursor / starting point

- There is no spec/requirement artifact anywhere in the codebase today (verified
  against `docs/` and the extension-point catalog) — "plans" are execution task
  lists (E16-S2), not requirements documents. E20 starts from zero on content,
  but every mechanism it needs has a template: manifest validator + published
  schema (E1-S1/E3-S1 pattern), tenant-scoped dual-backend persistence
  (ADR-010), approval state machine (E16-S2), append-only event catalog
  (E9-S3), ContextProvider (E7-S4).
- The constitution interop target formats (`AGENTS.md`, `CLAUDE.md`) already
  exist as ecosystem conventions; the export bridge is a renderer, not a new
  contract.

## Epic exit checklist

- [ ] All 5 stories meet the global DoD (`../templates/dod_checklist.md`) plus
      their story-specific DoD above.
- [ ] Contract tests green for `spec.yaml`/constitution validation, the
      registry lifecycle, the change-proposal model, and the Spec Context
      Provider.
- [ ] RFC-007 accepted and the epic ADR (spec contract & registry boundary)
      filed before E20-S1 implementation starts (`agent_guide.md` §5).
- [ ] `spec.*` events documented append-only in the event catalog.
- [ ] `docs/v2_platform/progress.md` updated.
