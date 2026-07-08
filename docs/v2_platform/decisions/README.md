# Decisions Log (ADR / RFC)

This directory is the decision log for the v2 platform refactor. It holds the two
complementary instruments defined in `docs/architecture/v2_platform_reference.md` §19.3:

- **RFC (Request for Comments)** — a formal proposal opened for discussion **before**
  a change that affects contracts, extension points, `/v2` APIs, events, the data
  model, or security policy. Lifecycle: `Draft -> Under review -> Accepted/Rejected ->
  Implemented`.
- **ADR (Architecture Decision Record)** — an immutable record of a decision and its
  context/consequences, written once the decision is fixed (often when an RFC is
  accepted). ADRs are numbered sequentially and are never rewritten: a later change is
  recorded as a new ADR that **supersedes** the previous one.

## When each is required

Per §19.1/§19.3 of the reference doc: any change that causes a **MAJOR** version bump
of a platform artifact (core, plugin, agent, skill, flow, eval, API, event) requires an
accepted RFC and a corresponding ADR. A **MINOR** change to a public contract does not
require an RFC but should still record a lightweight ADR. **PATCH** changes require
neither.

## How to add one

1. Copy `docs/v2_platform/templates/rfc_template.md` (if a proposal needs discussion
   first) or `docs/v2_platform/templates/adr_template.md` (if the decision is already
   made) into this directory.
2. Name the file `RFC-<NNN>-<slug>.md` or `ADR-<NNN>-<slug>.md`, using the next
   sequential number for that instrument (check the index table below).
3. Reference the epic(s) (`E<n>`) and story/stories (`E<n>-S<m>`) it relates to.
4. Add a row to the index table below in the same PR.
5. If an ADR supersedes a previous one, set the old ADR's `Status` to `Superseded by
   ADR-<NNN>` — do not delete or rewrite it.

## Index

| ID | Title | Status | Epic | Date |
| --- | --- | --- | --- | --- |
| ADR-001 | PostgreSQL as Default Production State Store | Accepted | E0-S3 | 2026-07-03 |
| RFC-001 | Plugin Extension-Point Catalog | Accepted | E1-S1 | 2026-07-04 |
| ADR-002 | Plugin Manifest and Extension Catalog | Accepted | E1 | 2026-07-04 |
| ADR-003 | Agent Manifest and Initial Capability Vocabulary | Accepted | E2-S1 | 2026-07-04 |
| RFC-002 | Flow Manifest Specification (`flow.yaml`) | Accepted | E3-S1 | 2026-07-05 |
| ADR-004 | Flow Manifest and Node-Type Vocabulary | Accepted | E3-S1 | 2026-07-05 |
| ADR-005 | Determinism Boundary for Flow Replay | Accepted | E3-S3 | 2026-07-05 |
| ADR-006 | Budget Propagation for Composite Nodes | Accepted | E3-S5 | 2026-07-05 |
| RFC-003 | Reasoning Strategy Contract (`reasoning.strategy`) | Accepted | E4-S1 | 2026-07-05 |
| ADR-007 | Reasoning Engine Boundary and Enforcement Model | Accepted | E4-S1 | 2026-07-05 |
| RFC-004 | Router & Selector Contract (`router`, `selector`) | Accepted | E5-S1 | 2026-07-05 |
| ADR-008 | Router & Selector Boundary and Enforcement Model | Accepted | E5-S1 | 2026-07-05 |
| RFC-005 | Evaluation Service Contract (`eval.yaml`, `Evaluator`) | Accepted | E5-S3 | 2026-07-05 |
| ADR-009 | Evaluation Service Boundary and Scope | Accepted | E5-S3 | 2026-07-05 |
| ADR-010 | Scoped E8-S1 Tenancy Slice for E7 (Down Migrations + tenant_id/RLS) | Accepted | E7 (E8-S1 slice) | 2026-07-06 |
| ADR-011 | pgvector HNSW Index for Code Chunk Embeddings | Accepted | E7-S2 | 2026-07-06 |
| RFC-006 | Frontend redesign — Execution Control Center | Draft | E15–E17 | 2026-07-08 |

> Update this table whenever an ADR or RFC is added or changes status. This index,
> together with `docs/v2_platform/progress.md`, is the fastest way to see which
> architectural decisions already exist before starting new work.
