# E12 — Quality & Evals

**Wave:** Split — E12-S1 (test pyramid) and the start of E12-S2 (contract tests for
existing extension points) target Alpha; E12-S2 completion plus E12-S3/S4 (agent
evals, CI quality gates) target Beta.
**Status:** In progress · **Stories:** 1/4 complete (E12-S1 done)
**Depends on:** E0, E1-E6, E5
**Enables:** E13 (Marketplace requires green contract tests to publish); mandatory contract tests for the Beta extension points `execution_environment` (E32, ADR-013) and `secret_backend` (E33, ADR-014) under E12-S2
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.7.6 (E12), §18.8, §18.9

## Objective

Establish the test pyramid, mandatory **contract tests** for extension points,
**agent evals** via the **Evaluation Service**, and CI **quality gates**.

## Key result

No change lands without passing the Validation Gates; extensions only integrate with a
green contract test; agent/routing quality is measured and fed back.

## Stories

### E12-S1 — Test pyramid and coverage (done)

Subtasks:
- [x] `E12-S1-T1`: unit/integration/e2e suites organized by subsystem
      (`backend/tests/unit/<subsystem>/`, `backend/tests/integration/`,
      `frontend/e2e/`).
- [x] `E12-S1-T2`: core coverage >= 85% with a CI gate. "Core" = `backend/`
      excluding `backend/tests/*`; enforced via `make test-backend` /
      `.github/workflows/ci-backend.yml`
      (`--cov=backend --cov-fail-under=85`, `backend/tests/*` omitted via
      the root `.coveragerc`), with a
      coverage summary published on every PR
      (`scripts/ci_coverage_summary.py` → `$GITHUB_STEP_SUMMARY` +
      `backend-coverage-report` artifact). Product coverage measured at
      88.29% (raw coverage including test code is ~93%, which is why the
      omit is required for the gate to be meaningful).
- [x] `E12-S1-T3`: deterministic data/fixtures and a stub provider for tests
      (`StubLLMProvider` in `backend/agents/provider.py`; no network/live
      services in the unit tier).

A dedicated smoke e2e CI job (`.github/workflows/ci-e2e.yml`) boots the
backend (SQLite local-first mode), health-probes `/docs`, then runs the
Playwright frontend suite (`cd frontend && npm run e2e`), replacing the
previous lightweight `smoke-e2e` job that only curled `/health`.

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

- Backend CI (ruff + mypy + pytest) and frontend CI (lint + typecheck + vitest) were
  already `default` (`.github/workflows/ci-backend.yml`, `ci-frontend.yml`) — a solid
  base for E12-S1. E12-S1 added the 85% product-code coverage gate (previously
  `planned`, tracked as Unit 22 in `docs/implementation/mvp_refactor_plan.md`) and a
  dedicated smoke e2e job (`ci-e2e.yml`); infra/docs validation beyond this remains
  out of scope for E12-S1.
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
