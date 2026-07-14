# E26 — Agent Runtime Context Engineering

**Wave:** v2.2 — Concept Integration (may start once E2/E3 are stable; no
v2.1 dependency).
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E2 (Agent Runtime), E3 (Flow Engine), E8 (State Store);
E26-S4 loop-policy options additionally consume E23-S2 when present.
**Enables:** E30-S1 (estimation uses the cache-hit model), E29 (external
memory feeds the knowledge library), cheaper long-horizon harness runs (E23).
**Canonical source:** `docs/architecture/v2_platform_reference.md` §23.2,
§18.7.18; RFC-008

## Objective

Make the Agent Runtime **cost- and coherence-aware by contract**: KV-cache-
friendly invariants (stable prefixes, append-only context, deterministic
serialization) that are measured, a pluggable `condenser` extension point for
context compaction, tool masking instead of mid-run tool removal, and
external-memory primitives (State-Store/workspace notes with reversible
compression, plan recitation, keep-errors-in-context) so long tasks stay
coherent without unbounded context growth.

## Key result

A 50+-step agent run whose measured prompt-cache hit rate stays high (stable
prefix never invalidated by the platform), whose context never exceeds its
configured budget because condensers compress history losslessly-enough to
continue, and whose plan, notes, and past errors survive compaction via
durable external memory — at an input-token cost measurably below the
uncompacted baseline.

## Prior art (condensed)

Manus context-engineering lessons (KV-cache hit rate as the production
metric; append-only immutable context; deterministic serialization; logit
masking over tool removal; filesystem as reversible external memory; todo
recitation; keep errors in context), Anthropic effective-context-engineering
(compaction, structured note-taking, just-in-time retrieval), OpenHands
condensers (pluggable threshold-triggered history compression), Claude Code
five-stage progressive compaction, context-rot measurements. Sources and
evidence grades in RFC-008.

## Stories

### E26-S1 — KV-cache-aware runtime invariants & metric

Subtasks:
- `E26-S1-T1`: runtime contract — the Agent Runtime guarantees: stable
  system/tool prefix per run (no timestamps or mutable data in the prefix),
  append-only message history (no in-place edits before the cache point),
  deterministic serialization of tool defs and structured payloads (stable
  key ordering).
- `E26-S1-T2`: cache-hit-rate metric — per-call cached vs uncached input
  tokens (from provider usage fields where available; estimated otherwise),
  aggregated per run/tenant into the E2 metric families; surfaced in run
  detail.
- `E26-S1-T3`: contract test fixtures that detect prefix invalidation
  (mid-run tool-def mutation, non-deterministic serialization) and fail.

| Criterion | Detail |
| --- | --- |
| Functional | A run that mutates tool defs mid-iteration fails the contract test; cache-hit metrics visible per run via `/v2` run detail |
| Non-functional | Invariants add no per-call latency beyond serialization; metric works with the offline stub provider (estimated mode) |
| DoR (specific) | RFC-008 accepted; epic ADR (runtime context contract & condenser boundary) filed |
| DoD (specific) | Contract tests incl. invalidation fixtures; `docs/runtime/context.md` |
| Dependencies | E2-S3/S4 |

### E26-S2 — `condenser` extension point

Subtasks:
- `E26-S2-T1`: `condenser` extension-point kind (RFC-001 catalog, additive)
  — invoked by the runtime before an LLM call when a trigger trips
  (event-count, token-budget, or cost threshold); receives the event
  history, returns a compacted history; must preserve the first-N pinned
  events and last-M recent events untouched.
- `E26-S2-T2`: two reference condensers — threshold summarization (summarize
  all but pinned head + recent tail via a cheap model) and progressive
  compaction (staged budget reduction before summarization).
- `E26-S2-T3`: condensation events (`context.condensed` with before/after
  token counts) appended to the run event stream for auditability.

| Criterion | Detail |
| --- | --- |
| Functional | A long run crossing the trigger continues correctly after condensation; pinned head and recent tail are byte-identical; every condensation is an auditable event |
| Non-functional | Condenser plugins pass the mandatory contract test; condensation cost is metered against the run budget (ADR-006) |
| DoR (specific) | E26-S1 available (condensation must not break prefix invariants) |
| DoD (specific) | One test per reference condenser incl. a context-budget-exceeded fixture; `docs/runtime/condensers.md` |
| Dependencies | E26-S1, E1 (extension catalog), E5 (cheap-model selection) |

### E26-S3 — Tool masking over removal

Subtasks:
- `E26-S3-T1`: tool-router masking — constraining the action space marks
  tools unavailable (masked) instead of removing their definitions mid-run;
  masked tools are rejected fail-closed if called.
- `E26-S3-T2`: consistent tool-name prefixes (`<plugin>__<tool>` already per
  E1) leveraged for group masking (mask a whole capability family in one
  rule).
- `E26-S3-T3`: provider capability probe — where a provider supports logit
  bias/allowed-tools natively, the adapter uses it; otherwise masking is
  enforced post-hoc by the runtime (reject + structured error kept in
  context per E26-S4).

| Criterion | Detail |
| --- | --- |
| Functional | Masking mid-run does not invalidate the measured cache prefix (E26-S1 metric unchanged); calling a masked tool yields a fail-closed structured error |
| Non-functional | Masking rules composable with the E1 permission broker (deny wins) |
| DoR (specific) | E26-S1 metric available to prove non-invalidation |
| DoD (specific) | Masking + cache-stability test; `docs/runtime/tool-masking.md` |
| Dependencies | E26-S1, E1, E2-S4 |

### E26-S4 — External memory primitives & loop-policy options

Subtasks:
- `E26-S4-T1`: external memory — durable run notes (State Store) and
  workspace files usable as agent memory with **reversible compression**:
  context keeps references (paths/IDs) + short summaries, full content
  restorable on demand through a retrieval tool.
- `E26-S4-T2`: plan recitation — an optional runtime behavior (and E23
  loop-policy option `recitation`) that re-appends the current plan/checklist
  at a configured cadence so goals stay in recent attention.
- `E26-S4-T3`: keep-errors-in-context — failed actions and their structured
  errors are retained (not scrubbed) up to a configurable cap; condensers
  must preserve error summaries; exposed as E23 loop-policy option
  `keep_errors`.

| Criterion | Detail |
| --- | --- |
| Functional | A fresh-context iteration (E23-S2) reconstructs working state from notes + references alone; recitation demonstrably re-appends the live plan; a repeated-failure fixture shows the error record surviving condensation |
| Non-functional | Restored content metered against the run budget; notes tenant-scoped (E8-S1 RLS) |
| DoR (specific) | E26-S2 available; E23-S2/S3 contracts reviewed (options are additive) |
| DoD (specific) | Reconstruction + recitation + error-retention tests; `docs/runtime/memory.md` |
| Dependencies | E26-S2, E8, E23-S2/S3 (option wiring, additive) |

## v1/v2 precursor / starting point

- The E2 Agent Runtime already owns provider mediation, budgets, and
  per-step traces — but makes no promises about prefix stability, history
  mutation, or serialization determinism, and has no compaction seam: today
  a long run simply grows until budgets stop it.
- E23-S3's durable checklist/journal is the harness-level state; E26-S4
  generalizes the mechanism to any agent run and adds the
  reference+restore (reversible compression) pattern.
- The E1 permission broker already denies tools; it removes rather than
  masks, which is exactly the cache-hostile behavior E26-S3 replaces.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD plus story-specific DoD above.
- [ ] Contract tests green for runtime invariants, the `condenser` kind,
      masking, and external memory.
- [ ] Epic ADR (runtime context contract & condenser boundary) filed before
      E26-S1 implementation starts.
- [ ] `context.*` events documented append-only in the event catalog.
- [ ] `docs/v2_platform/progress.md` updated.
