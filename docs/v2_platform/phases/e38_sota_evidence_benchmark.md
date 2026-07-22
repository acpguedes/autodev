# E38 — SOTA Evidence Matrix & Capability Benchmark

**Wave:** v2.3 — Platform Excellence (after E12-S2; benchmark execution depends
on E20-E27, but the evidence matrix can start immediately).
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E12, E20-E23, E27, E28; evidence-matrix story depends on RFC-008
only.
**Enables:** credible comparison with large agentic coding platforms, honest
benchmark reporting, and de-risked SOTA adoption.

## Objective

Convert SOTA inspiration into an evidence-governed program. Every imported
concept must identify evidence quality, transferability, risks, success metrics
and the epic/story that will implement or reject it. Platform quality must be
reported through a self-hostable capability benchmark rather than anecdotal demos.

## Key result

AutoDev can publish release-to-release capability reports covering success,
verified success, cost, wall time, human interventions, context leakage, oracle
disagreement and rollback rate across representative tasks.

## Stories

### E38-S1 — SOTA evidence matrix

Subtasks:
- `E38-S1-T1`: create `docs/v2_platform/sota_evidence_matrix.md` with concept,
  exemplar/source, evidence type, confidence, transferability, risk,
  destination epic/story and metric.
- `E38-S1-T2`: move broad comparative claims from RFC-008 into the matrix or
  mark them as inference when direct evidence is unavailable.
- `E38-S1-T3`: require new SOTA concepts to pass the matrix before becoming an
  epic/story.

| Criterion | Detail |
| --- | --- |
| Functional | Every RFC-008 concept has a disposition, evidence grade and adoption target |
| Non-functional | Claims are concise, source-backed where possible, and vendor-neutral |
| DoR (specific) | RFC-008 reviewed |
| DoD (specific) | Matrix linked from RFC-008 and progress tracker |
| Dependencies | RFC-008 |

### E38-S2 — AutoDev Capability Benchmark contract

Subtasks:
- `E38-S2-T1`: define benchmark task categories: SDD greenfield, SDD
  brownfield, bugfix, refactor, UI/browser verification, security hardening,
  migration, dependency-hallucination, multi-agent handoff and long-horizon
  harness execution.
- `E38-S2-T2`: define metrics: success, verified success, cost, wall time,
  token burn, human decisions, context leakage, rollback rate, oracle
  disagreement, reproducibility and local-first pass/fail.
- `E38-S2-T3`: define task-pack manifest and decontamination/rotation policy.

| Criterion | Detail |
| --- | --- |
| Functional | A benchmark task pack can be run locally through the harness/eval stack |
| Non-functional | No paid provider is required for the baseline stub/local-model track |
| DoR (specific) | E12 eval contracts available |
| DoD (specific) | `docs/evals/capability_benchmark.md`; manifest schema draft |
| Dependencies | E12, E23 |

### E38-S3 — Benchmark harness integration

Subtasks:
- `E38-S3-T1`: map each benchmark category to a named harness pattern from
  E37 and to executable gates from E22/E27.
- `E38-S3-T2`: require benchmark reports to include harness configuration,
  model/provider profile, budgets and degradation mode.
- `E38-S3-T3`: add held-out task handling and result retention for audit.

| Criterion | Detail |
| --- | --- |
| Functional | Benchmark reports are reproducible from persisted harness/eval records |
| Non-functional | Public comparison claims disclose configuration and budget |
| DoR (specific) | E37 pattern catalog and E27 verifier contracts available |
| DoD (specific) | Report format and benchmark-harness mapping documented |
| Dependencies | E23, E27, E37 |

### E38-S4 — Release scorecard and competitive readiness gate

Subtasks:
- `E38-S4-T1`: define a release scorecard with capability deltas since the
  previous release and regressions requiring waiver.
- `E38-S4-T2`: feed scorecard output into GA and post-GA release gates.
- `E38-S4-T3`: publish a self-hostable sample benchmark pack for OSS users to
  reproduce claims.

| Criterion | Detail |
| --- | --- |
| Functional | GA cannot claim competitive readiness without a benchmark scorecard |
| Non-functional | Scorecards separate measured results from roadmap claims |
| DoR (specific) | E38-S2/S3 available |
| DoD (specific) | Release scorecard template linked from E13 and progress gates |
| Dependencies | E13, E38-S3 |

## Epic exit checklist

- [ ] All 4 stories meet the global DoD plus story-specific DoD above.
- [ ] Evidence matrix, benchmark contract and release scorecard are linked from RFC-008/E12/E13.
- [ ] `docs/v2_platform/progress.md` updated.
