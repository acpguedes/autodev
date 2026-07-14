# E27 — Execution-Grounded Verification & Test-Time Compute

**Wave:** v2.2 — Concept Integration (contract stories after E22/E23;
execution-dependent stories additionally gated on E14 and E12).
**Status:** Not started · **Stories:** 0/5 complete
**Depends on:** E5 (Selector/Evaluation), E22 (verification gates, acceptance
compiler), E23 (harness, candidate race), E14 (real execution + sandbox),
E12 (eval infrastructure)
**Enables:** E30-S3 (draft→final tiers reuse candidate selection), higher
harness `success` precision platform-wide
**Canonical source:** `docs/architecture/v2_platform_reference.md` §23.3,
§18.7.19; RFC-008

## Objective

Make **execution-grounded verification and test-time compute** first-class:
best-of-N candidate generation with execution-based selection as a named
harness strategy, multi-verifier composition with calibrated multi-sample
LLM judges, a cross-model second opinion ("oracle") that only a
model-agnostic plane can offer, property-based acceptance oracles, and
hardening against reward hacking and weak test oracles — plus the internal
evaluation methodology (decontaminated, held-out, resource-aware) that keeps
the platform honest.

## Key result

For a spec-derived task, the platform generates N candidate patches (varying
agent/model/strategy via the E5 Selector), executes each against compiled
acceptance tests in the sandbox, composes verifier verdicts (execution
primary; calibrated judges only for non-executable dimensions; optionally a
distinct-provider oracle), and selects a winner with the full decision trace
persisted — while an oracle-hardening pass demonstrates that weak-test
"lucky passes" are detected rather than accepted.

## Prior art (condensed)

Agentless (localize → generate-N → select-by-tests beats elaborate agency on
cost-adjusted quality), RLEF/RLVR (execution feedback as the durable reward
signal), UTBoost (~31% of benchmark passes survive only inadequate oracles),
"Building to the Test" (reward hacking is systemic), judge-reliability
studies (single judge calls are noisy; multi-sample + calibration required),
Amp's Oracle (a deliberately different frontier model as second opinion),
Jules critic pass, Cursor race pattern (raced in E23-S4; selection
generalized here), SWE-rebench/SWE-Effi (decontaminated, resource-aware
evaluation). Sources and evidence grades in RFC-008.

## Stories

### E27-S1 — Best-of-N candidate generation & execution-based selection

Subtasks:
- `E27-S1-T1`: candidate-set contract — a harness (or flow node) requests N
  candidates for one task; each candidate is a normal isolated run
  (E23-S4 worktree/claiming reused), varying agent/model/strategy via E5
  Selector policy; `candidate.*` events (`candidate.generated`,
  `.verified`, `.selected`) appended.
- `E27-S1-T2`: execution-based selection — compiled acceptance tests
  (E22-S1) run against every candidate in the sandbox; selection ranks by
  gate verdicts first, tie-breaking via E5 evals; the losing candidates'
  runs and diffs are retained for comparison.
- `E27-S1-T3`: budget semantics — the candidate set draws from one parent
  budget fail-closed (ADR-006); partial sets (budget exhausted at k < N)
  select among the k verified candidates.

| Criterion | Detail |
| --- | --- |
| Functional | A race of N candidates yields exactly one winner chosen by execution verdicts with the decision trace inspectable; losers retained; a candidate that fails compilation/tests is never selectable over one that passes |
| Non-functional | Aggregate cost capped by the parent budget (cannot overspend); N is a policy parameter, not code |
| DoR (specific) | RFC-008 accepted; epic ADR (candidate/verifier contracts, judge calibration policy) filed; E23-S4 race mechanics reviewed |
| DoD (specific) | Selection, partial-set, and budget-cap tests; `docs/verification/candidates.md` |
| Dependencies | E23-S4, E22-S1, E5, E14-S4 |

### E27-S2 — Multi-verifier composition & calibrated LLM judges

Subtasks:
- `E27-S2-T1`: verifier-set contract — a selection decision may compose
  multiple verifiers (execution gates, static checks, evals, judges), each
  with a declared dimension and weight; execution verdicts are always
  primary and cannot be outvoted by judges (RFC-007 rule 2 preserved).
- `E27-S2-T2`: calibrated judge evaluator — extends the E5 llm-judge
  evaluator with multi-sample voting (k samples, agreement threshold),
  rubric versioning, and a persisted per-rubric calibration record
  (agreement rate over time); judges restricted to non-executable
  dimensions by contract.
- `E27-S2-T3`: verdict aggregation trace — the composed decision (which
  verifier said what, weights, final ranking) persisted per candidate and
  exposed in run detail.

| Criterion | Detail |
| --- | --- |
| Functional | A candidate failing execution is rejected regardless of judge scores; judge verdicts show sample count + agreement; aggregation trace reproducible from persisted data |
| Non-functional | Judge sampling cost metered per verdict; calibration records tenant-scoped |
| DoR (specific) | E27-S1 available; RFC-005 evaluator contract reviewed (additive) |
| DoD (specific) | Aggregation + judge-noise fixture tests (two runs, same verdicts); `docs/verification/verifiers.md` |
| Dependencies | E27-S1, E5, E12 |

### E27-S3 — Cross-model second opinion ("oracle" role)

Subtasks:
- `E27-S3-T1`: Selector policy vocabulary gains
  `distinct_provider_from: <role>` (additive MINOR per RFC-004) so a critic/
  oracle role is guaranteed to resolve to a different provider/model family
  than the actor role.
- `E27-S3-T2`: oracle verifier — a reference verifier (E27-S2 kind) that
  reviews the winning candidate's diff + evidence with the distinct model;
  configurable as advisory (vote) or blocking (veto) per gate tier
  (HARD/SOFT/AUTO semantics reused from E22).
- `E27-S3-T3`: degrade path — when only one provider is configured
  (self-hosted single-model installs), the oracle degrades to a distinct
  strategy/temperature profile with the degradation recorded, never
  silently skipped.

| Criterion | Detail |
| --- | --- |
| Functional | With two providers configured, actor and oracle demonstrably resolve to different providers; blocking mode prevents merge on oracle veto with the veto reason persisted; single-provider installs record the degradation |
| Non-functional | Oracle cost visible as a separate line in run cost breakdown |
| DoR (specific) | E27-S2 available; E5 Selector policy reviewed |
| DoD (specific) | Distinct-resolution, veto, and degrade tests; `docs/verification/oracle.md` |
| Dependencies | E27-S2, E5, E2-S4 |

### E27-S4 — Property-based acceptance oracles

Subtasks:
- `E27-S4-T1`: property compiler — extends the E22-S1 acceptance compiler:
  requirements whose acceptance criteria are universally quantified
  ("for any…") compile to property-based tests (Hypothesis for the
  Python/pytest target) instead of, or in addition to, example-based tests.
- `E27-S4-T2`: property review gate — generated properties are themselves
  artifacts bound to requirement IDs, reviewable/editable in the spec
  change flow (E20 deltas) before they gate anything.
- `E27-S4-T3`: shrinking + counterexample persistence — failing properties
  persist the shrunk counterexample into the evidence bundle (E22-S5).

| Criterion | Detail |
| --- | --- |
| Functional | A universally-quantified acceptance clause yields a runnable property test traced to its `R-<n>`; a seeded bug is caught by the property and the shrunk counterexample appears in the evidence bundle |
| Non-functional | Property runs bounded (examples/time) by gate budget; deterministic for frozen seeds (ADR-005) |
| DoR (specific) | E22-S1 compiler available; EARS grammar decision (RFC-007 open question) resolved for quantified clauses |
| DoD (specific) | Compile + catch + shrink tests; `docs/verification/properties.md` |
| Dependencies | E22-S1, E20, E14-S4 |

### E27-S5 — Oracle hardening & internal evaluation methodology

Subtasks:
- `E27-S5-T1`: weak-oracle detection — differential augmentation of
  compiled acceptance tests (mutation-style perturbations of the candidate
  patch must flip at least one test; a suite nothing can fail is flagged);
  "lucky pass" candidates (pass with unexecuted changed lines) flagged for
  review.
- `E27-S5-T2`: anti-reward-hacking checks — candidates that modify tests,
  gate configs, or spec files to reach `success` are rejected fail-closed
  unless the change flows through the spec change process (E20 deltas).
- `E27-S5-T3`: internal eval methodology (executed by E12) — held-out,
  decontaminated task sets; scores reported with the harness configuration
  disclosed and under explicit token/time budgets; public benchmark claims
  follow the same discipline.

| Criterion | Detail |
| --- | --- |
| Functional | A tautological test suite is flagged; a candidate that edits a test to pass is rejected with a traced reason; internal eval reports include harness config + resource budget |
| Non-functional | Augmentation cost bounded per gate budget; methodology documented as policy, not code |
| DoR (specific) | E27-S1 available; E12 eval infra scoped (this story shapes its methodology) |
| DoD (specific) | Weak-oracle, reward-hack, and report-format tests; `docs/verification/hardening.md` |
| Dependencies | E27-S1, E22, E12, E20 |

## v1/v2 precursor / starting point

- E23-S4 already races N candidates and picks a winner via gates/evals; E27
  generalizes that into named, reusable contracts (candidate sets, verifier
  composition, selection traces) usable by any flow, not just harness races.
- The E5 Evaluation Service already runs deterministic and llm-judge
  evaluators; E27-S2 adds multi-sampling/calibration, and E27-S3's
  `distinct_provider_from` is a Selector policy extension, not a new engine.
- The E22 acceptance compiler emits example-based tests; E27-S4 adds the
  property-based class the research identifies as the stronger oracle.
- Nothing today measures oracle strength or detects reward hacking — E27-S5
  is genuinely new and also fixes the methodology E12 will operate under.

## Epic exit checklist

- [ ] All 5 stories meet the global DoD plus story-specific DoD above.
- [ ] Contract tests green for candidate sets, verifier composition, oracle
      role, property compilation, and hardening checks.
- [ ] Epic ADR (candidate/verifier contracts, judge calibration policy)
      filed before E27-S1 implementation starts.
- [ ] `candidate.*` events documented append-only in the event catalog.
- [ ] `docs/v2_platform/progress.md` updated.
