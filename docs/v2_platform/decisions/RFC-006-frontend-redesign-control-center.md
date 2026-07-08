# RFC-006: Frontend redesign — Execution Control Center

- **Status:** Accepted (2026-07-08)
- **Author(s):** AutoDev Architect maintainers          **Date:** 2026-07-08
- **Reviewers:** TBD
- **Epic(s):** E15, E16, E17                 **Stories:** E15-S1..S4, E16-S1..S5, E17-S1..S5 (14 stories total)
- **Comment deadline:** 2026-07-22

## Summary

This RFC records the decision to readapt the E10 frontend to the redesign
prototype captured in `layout_prototype_brainstorm/` (`Autodev Redesing.html`,
`AutoDev - Project Description.pdf`, and the screenshots in `Frontend
redesign proposal.zip` → `shots/`) through three staged, planning-only epics
inserted logically after E10 and executed before E11 kicks off:

- **E15 — Design Language & App Shell**
- **E16 — Control-Plane API Enablement**
- **E17 — Control Center Screens**

Together these epics cover 14 stories. This RFC is planning-only: it fixes
the scope, numbering, and sequencing of E15–E17; it does not itself change
any contract, endpoint, or UI code.

## Motivation

Per the project description PDF, the E10 frontend (dark navy palette, no
shared component library) suffers from low contrast and unclear information
hierarchy, which hurts trust and readability during long agent-execution
sessions. The redesign proposes an editorial, calm "execution control
center" aesthetic — inspired by the serenity of NotebookLM — with high
contrast, clear navigation, and generous whitespace, while preserving the
developer-grade technical density the platform's operators need (execution
timelines, plan gates, patch diffs, provider/session state). This directly
serves the repository's "transparent docs" and "API-first" principles: the
redesign must be driven by `/v2` contracts rather than ad hoc UI state, and
must be documented before implementation begins.

## Proposed design

### E15 — Design Language & App Shell

- New design tokens: warm-paper light theme (`#faf8f4` background) and
  charcoal dark theme (`#100f12` background), with an iris accent
  (`#5a4fe0` light / `#8e88ff` dark).
- Typography system: Newsreader (editorial serif for headings/prose),
  Instrument Sans (UI sans), JetBrains Mono (code/log/diff surfaces).
- Three-region application shell: a 250px sidebar rail (primary navigation +
  provider status card), a 64px contextual header, and a dismissible 400px
  execution panel for live agent activity.
- Migration of legacy CSS from the E10 design system onto the new tokens and
  shell, plus the i18n foundation (see "Companion decisions recorded"
  below) that E17 screens will consume.

### E16 — Control-Plane API Enablement

API-first parity work so every E17 screen is backed by a versioned `/v2`
capability before any screen is built, per this repository's API-first
principle and `docs/architecture/v2_platform_reference.md` §2.13:

- Chat and execution-timeline events (origin E9-S2 events model, E3
  orchestration engine, E2 agent framework) exposed for streaming
  consumption by the execution panel and chat view.
- Plan step-level approval gates (origin E3 orchestration engine, E9-S1
  Control Plane API) so the Plans screen can request/display/act on
  per-step approvals.
- Patches review and apply, including dry-run (origin E0 foundations, E9-S1
  Control Plane API, E14 real execution governance).
- A unified extensions catalog plus provider configuration/status surface
  (origin E1 plugin core, E2 agent framework, E6 skills v2, E9-S4 MCP/API
  surface, E5 routing/selection/evaluation).

Adjustments to these already-Done epics (E1–E9) are expressed as new E16
stories that cite their origin epic; the originating epics themselves are
not reopened (see "Companion decisions recorded").

### E17 — Control Center Screens

The seven prototype views, built on the E15 shell and the E16 API surface:

1. Chat execution view (streaming chat + execution timeline).
2. Plans view with step-level approval gates.
3. Patches review (diff + dry-run + apply).
4. Sessions and configuration.
5. Extensions hub (catalog + provider status).
6. Flow-builder alignment with the existing visual flow editor
   (origin E10-S3, E3-S6).
7. A landing/overview screen tying the above together (execution control
   center home).

### Contracts and compatibility

- **API change:** New `/v2` endpoints introduced by E16 stories are
  additive only (new routes/fields under existing `schemaVersion` families);
  no existing `/v2` response shape is removed or narrowed by this RFC.
- **hostApi/SemVer change:** None proposed by this RFC directly — each E16
  story that adds a contract will carry its own SemVer classification
  (expected MINOR, additive) per §19.1, decided in that story's own ADR.
- **Data migrations:** None required for the planning insertion itself; any
  migration needed by an E16 story is scoped and versioned within that
  story.

## Alternatives considered

- **Decimal epic numbering (e.g. E10.1, E10.2, E10.3).** Rejected: it breaks
  the flat `E<n>` identifier convention used across the entire roadmap and
  in `docs/v2_platform/progress.md`.
- **Reopening E1–E9 and appending redesign stories to them.** Rejected: it
  pollutes epics that are already marked Done and mixes their completion
  status with unrelated, later-scoped UI work. Instead, E16 stories cite
  their origin epic for traceability without reopening it.
- **A single big-bang redesign epic.** Rejected in favor of three staged,
  thematic epics (design language, API enablement, screens) so each can be
  reviewed, gated, and (later) implemented independently, consistent with
  this repository's preference for explicit, incremental architecture over
  large undifferentiated changes.

## Impact

- **Security / RBAC / permissions:** No change proposed by this RFC; any
  RBAC implication of a specific E16 endpoint (e.g. patch-apply, approval
  gates) is assessed in that story's own ADR before implementation.
- **Observability (traces/metrics/events):** E16 stories are expected to
  extend, not replace, the existing E9-S2 event model; provider health
  observability is an open question (see below).
- **Cost / budgets / quotas:** None — this RFC is documentation/planning
  only.
- **Accessibility (if UI):** The E15 design language targets WCAG 2.2 AA
  contrast and navigation clarity as a stated motivation; conformance is
  verified when E15/E17 stories are implemented, not by this RFC.
- **Performance / SLOs:** None assessed at planning stage; streaming
  surfaces (chat, execution timeline) inherit the SLOs already defined for
  the underlying E9 event/API contracts.

## Implementation and rollout plan

This RFC covers the planning insertion only. Per governance
(`docs/v2_platform/agent_guide.md` §5, following the E14 precedent),
implementation of any E15–E17 story requires its own accepted ADR before
work begins. Proposed sequencing:

1. **E15** (Design Language & App Shell) lands first — it is the foundation
   every E17 screen renders on.
2. **E16** (Control-Plane API Enablement) lands second, in parallel where
   possible with late E15 work — it is the contract surface every E17
   screen consumes.
3. **E17** (Control Center Screens) lands last, consuming both.

All three epics are sequenced after E10 and complete before the E11
(Observability, Security & Multi-tenancy) kickoff. Each epic's stories,
acceptance criteria, and phase documentation are authored separately under
`docs/v2_platform/phases/e15_*.md`, `e16_*.md`, `e17_*.md`.

## Open questions

- Exact i18n library choice for the English-default / pt-BR bilingual UI
  (see companion decision on UI language below).
- Whether provider health surfaces via the existing metrics pipeline or
  requires a new dedicated endpoint in E16.
- Scope of Storybook (or equivalent component-doc tooling) coverage for the
  redesigned E17 screens.

## Companion decisions recorded by this RFC

1. **UI language:** English is the default UI language, with multilingual
   support (English + pt-BR) delivered via an i18n foundation in E15. The
   pt-BR prototype (`Autodev Redesing.html`) remains the visual/structural
   reference for layout and component design, independent of the
   default-language decision.
2. **Epic numbering:** E15–E17 are a sequential append, following the E14
   precedent — no decimal or lettered numbering. Each epic's phase doc
   carries `Wave` and `Depends-on` fields expressing its logical position
   after E10 and before E11.
3. **Handling of prior epics E1–E9:** Any adjustment the redesign needs from
   an already-Done epic is expressed as an E16 story that cites the origin
   epic (e.g. "origin E9-S2"); Done epics are not reopened or amended in
   place.
4. **Execution order:** E15 → E16 → E17, all completing before the E11
   kickoff.
