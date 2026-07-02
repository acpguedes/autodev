# E12 — Quality & Evals

**Wave:** Split — E12-S1 (test pyramid) and the start of E12-S2 (contract tests for
existing extension points) target Alpha; E12-S2 completion plus E12-S3/S4 (agent
evals, CI quality gates) target Beta.
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E0, E1-E6, E5
**Enables:** E13 (Marketplace requires green contract tests to publish)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.7.6 (E12), §18.8, §18.9

## Objective

Establish the test pyramid, mandatory **contract tests** for extension points,
**agent evals** via the **Evaluation Service**, and CI **quality gates**.

## Key result

No change lands without passing the Validation Gates; extensions only integrate with a
green contract test; agent/routing quality is measured and fed back.

## Stories

### E12-S1 — Test pyramid and coverage

Subtasks:
- `E12-S1-T1`: unit/integration/e2e suites organized by subsystem.
- `E12-S1-T2`: core coverage >= 85% with a CI gate.
- `E12-S1-T3`: deterministic data/fixtures and a stub provider for tests.

| Item | Content |
| --- | --- |
| CF | Per-layer tests run in CI; coverage reported; the stub guarantees determinism |
| CNF | Core >= 85% of lines; stable suite (no blocking flakiness) |
| DoR | E0 (base CI) ready; test strategy approved |
| DoD | Coverage gate active; report on every PR; testing docs |
| Dependencies | E0 |

### E12-S2 — Extension-point contract tests

Subtasks:
- `E12-S2-T1`: contract-test harness per Extension Point (plugin, agent, skill, provider).
- `E12-S2-T2`: `hostApi` (SemVer) compatibility verification.
- `E12-S2-T3`: mandatory gate for Marketplace publication.

| Item | Content |
| --- | --- |
| CF | Every extension point has a contract test; a contract incompatibility fails the build |
| CNF | Contract tests mandatory; execution within the agreed CI time budget |
| DoR | SemVer contracts published (E1-E6); harness defined |
| DoD | All extension points have a contract test; gate active; docs |
| Dependencies | E1, E2, E3, E4, E5, E6 |

### E12-S3 — Agent evals and closed feedback loop

Subtasks:
- `E12-S3-T1`: `eval.yaml` (dataset + rubric + metrics) executable offline/online.
- `E12-S3-T2`: Evaluation Service integration and result storage.
- `E12-S3-T3`: feedback into the Router & Selector.

| Item | Content |
| --- | --- |
| CF | Evals run in CI and on demand; results persisted; scores feed routing |
| CNF | Reproducible from a versioned dataset; observable execution |
| DoR | E5 (Evaluation Service) ready; eval datasets defined |
| DoD | Reference eval green; feedback to the Selector verified; docs |
| Dependencies | E5 |

### E12-S4 — CI quality gates (Validation Gates)

Subtasks:
- `E12-S4-T1`: chained lint/tests/coverage/security gates.
- `E12-S4-T2`: patch validation (dry-run, path guard) in the pipeline.
- `E12-S4-T3`: merge blocked without green gates.

| Item | Content |
| --- | --- |
| CF | Merge only with all gates green; patch validated by dry-run/path guard |
| CNF | Deterministic gates; clear failure feedback; CI time within the agreed budget |
| DoR | E12-S1..S3 ready; branch-protection policy defined |
| DoD | Gates applied on every PR; contribution docs updated |
| Dependencies | E12-S1, E12-S2, E12-S3 |

## v1 precursor / starting point

- Backend CI (ruff + mypy + pytest) and frontend CI (lint + typecheck + vitest) are
  already `default` (`.github/workflows/ci-backend.yml`, `ci-frontend.yml`) — a solid
  base for E12-S1, but there are no coverage gates yet (`planned`, tracked as Unit 22
  in `docs/implementation/mvp_refactor_plan.md`), no smoke e2e job, and no infra/docs
  validation.
- There is no contract-test harness, no agent evals, and no CI-enforced Validation
  Gate beyond lint/type/test today; E12-S2, E12-S3, and E12-S4 start from zero and are
  gated on E1-E6 and E5 respectively.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [ ] Every extension point declared across E1-E6 has a green contract test.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Alpha exit criterion "test pyramid + contract tests for existing extension
      points" (E12-S1, start of E12-S2) and Beta entry item "complete contract tests,
      agent evals, quality gates" (E12-S2 completion, E12-S3/S4) satisfied per §18.9.
