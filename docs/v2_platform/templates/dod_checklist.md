# Definition of Done (DoD) Checklists

> Source: `docs/architecture/v2_platform_reference.md`, §18.3 (global DoD) and Appendix (I).

## Global DoD (§18.3)

A Story only transitions to **Done** (Gate G5, see §18.1) once **all** of the following
are true and evidenced:

- [ ] **All functional acceptance criteria** verified by automated test.
- [ ] **Non-functional criteria** measured and within target (no SLO regression).
- [ ] **Tests passing** at every applicable level of the pyramid (unit -> integration -> e2e).
- [ ] **Coverage:** core >= 85% of lines; the touched area does not reduce global coverage.
- [ ] **Contract tests** mandatory and green for every extension point/endpoint/event touched.
- [ ] **Documentation updated** in `docs/` and the repo root (ADR/RFC when there is a decision; changelog; SDK examples).
- [ ] **Observability:** traces, metrics, and events emitted (OpenTelemetry) and visible on a dashboard; replay possible from persisted state.
- [ ] **Security:** RBAC applied; plugins with explicit permissions; sandbox with no network by default; `run_secret_scanning` clean; no critical-CVE dependencies.
- [ ] **Accessibility (when there is UI):** WCAG 2.2 AA verified; 100% keyboard navigation; contrast and focus validated; no a11y test regression.
- [ ] **Budgets:** execution paths respect token/cost/time/step ceilings and **fail closed**.
- [ ] **Migrations** versioned and reversible when possible; RPO <= 5 min / RTO <= 30 min preserved.
- [ ] **Feature flag** and rollback documented; release notes prepared.

## Per-item DoD checklist (Appendix I)

Copy this block into a story/subtask before marking it Done. All applicable items must
be checked.

```markdown
# Definition of Done (DoD) — <Story/Subtask ID: E<n>-S<m>[-T<k>]>

## Implementation and contracts
- [ ] All functional acceptance criteria met and demonstrated.
- [ ] Non-functional requirements met (p95 latency, budgets, WCAG 2.2 AA when UI).
- [ ] Contracts versioned correctly (SemVer/hostApi/schemaVersion) with no unannounced break.
- [ ] Manifests (plugin/agent/skill/flow/eval) validate against their schema.

## Quality
- [ ] Unit and integration tests added/updated (story-scoped; no unnecessary tests).
- [ ] Contract tests for extension points passing (mandatory).
- [ ] Core coverage >= 85% of lines maintained.
- [ ] Relevant evals executed and thresholds met.
- [ ] Lint, type-check, and CI quality gates green.
- [ ] English docstrings (description/args/returns/raises) and complete type hints
      on every new or changed package, class, method, and function (CONTRIBUTING.md §3).

## Branch hygiene (CONTRIBUTING.md §2)
- [ ] Story branch merged into the epic branch (`--no-ff`), epic branch pushed.
- [ ] Story branch deleted (local and remote).
- [ ] If this closes the epic: full suite green and PR opened from the epic branch to `main`.

## Security, observability, and data
- [ ] Minimal permissions reviewed; no hardcoded secrets; sandbox with no network by default.
- [ ] RBAC applied where required.
- [ ] Traces/metrics/events emitted and verified.
- [ ] Migrations versioned and reversible when possible (RPO/RTO respected).

## Delivery and documentation
- [ ] Documentation updated in `docs/` and the project root (behavior/architecture).
- [ ] ADR/RFC finalized/linked when there was an architectural decision.
- [ ] Code review approved; PR with a readable summary (kept separate from control metadata).
- [ ] Rollback/feature flag verified when applicable.
```
