# Beta Plan Audit — Gap Analysis (v2.0-beta)

> Scope of this audit: **documents only** (MDs under `docs/`), per
> instruction. No code was re-evaluated; all evidence below cites
> documents. Nothing was pushed to remote (no push/PR/merge).

## 1. Executive Summary

**Observed facts** (with documentary evidence):

1. The v2.0-beta gate (§18.9) requires "a real flow … validated in sandbox
   … with RBAC, budgets that fail closed, and end-to-end traces", but
   **no gate criterion requires fail-closed isolation proven by execution
   evidence** — strong isolation (classes, microVM) sits entirely in
   **E28 (v2.2)**, two waves after Beta.
   *Evidence:* `docs/architecture/v2_platform_reference.md` §18.9
   (v2.0-beta, criteria 1–9); `docs/v2_platform/phases/e28_execution_environments.md`.
2. **Secrets**: §16.1.2 defines secret management, but there is no
   epic/story in the Beta cut that delivers a store, plaintext-free
   injection, and redaction, and the Beta gate does not mention secrets.
   *Evidence:* §16.1.2; §18.9 (absence); epic table in
   `docs/v2_platform/progress.md`.
3. **Global install**: E14 includes `autodev` CLI install
   (`docs/execution/cli-install.md` planned), but there is no
   packaging/distribution/upgrade strategy, nor a clean-environment
   install gate criterion.
   *Evidence:* `docs/v2_platform/phases/e14_real_execution_governance.md`;
   §18.9 (absence).
4. Three architectural decisions that materially change the scope **are
   not recorded as an ADR**: isolation backend (container vs bubblewrap
   vs gVisor/microVM), secret store format, and global install strategy.
   Existing ADRs go up to ADR-012.
   *Evidence:* `docs/v2_platform/decisions/` (ADR-001..012, RFC-001..008).

**Recommendations** (absorbed into this plan):

- Create the Beta cut of the isolated environment as its own epic
  (**E32**), contract-first, with a pluggable backend and a pending
  decision in ADR-013 — E28 (v2.2) evolves this contract instead of
  introducing it.
- Create **E33** (Beta secrets: store, injection, redaction; ADR-014
  pending) and **E34** (packaging/install/upgrade; ADR-015 pending).
- Create **E35** to turn the Beta gate into a gate with mapped evidence,
  an executable acceptance flow, and a register of open decisions.
- Expand the v2.0-beta exit criteria (§18.9) with fail-closed isolation,
  plaintext-free secrets, and clean-environment install.

## 2. Gap Table

| # | Gap | Evidence (document) | Resolution | Priority |
| --- | --- | --- | --- | --- |
| G1 | Beta gate does not require proven isolation; strong isolation only in v2.2 (E28) | §18.9 v2.0-beta; `phases/e28_execution_environments.md` | E32 + gate criterion (10) | High |
| G2 | E14×E28 boundary with no defined Beta cut for "where it runs" | `phases/e14_real_execution_governance.md` (runner contract E14-S4, no environment layer) | "Relation to E14 and E28" section in E32 | High |
| G3 | Secrets with no Beta epic (store, injection, redaction) | §16.1.2; absence in §18.9 and in the epic table | E33 + gate criterion (11) | High |
| G4 | Global install with no packaging/upgrade strategy | `phases/e14_...md` (CLI UX only) | E34 + gate criterion (12) | Medium |
| G5 | Gate criteria with no evidence map (self-reporting possible) | §18.9 (criteria with no named evidence source) | E35-S1 (evidence map) | Medium |
| G6 | Negative paths (denial, budget, violation, revocation) outside the Beta acceptance definition | §18.9 criterion 1 (happy path only) | E35-S2 | Medium |
| G7 | Material architectural decisions with no ADR (isolation, secret store, install) | `decisions/` ends at ADR-012 | ADR-013/014/015 (Proposed, pending) + E35-S3 | High |
| G8 | Beta incident runbooks (isolation violation, leak, failed upgrade) missing | E11 runbook set (`phases/e11_...md`) | E35-S3-T3 | Low |
| G9 | Four domain stores raise `ValueError` on the PostgreSQL URL the `prod` profile mandates — quotas, secrets, execution policy, and environments cannot be constructed in production | `backend/config/settings.py:332-336` vs `quotas/store.py:49`, `secret_store/store.py:48`, `execution/policy.py:206`, `environments/store.py:38` | E49 + E51-E54 | High |
| G10 | `StepApprovalStore` silently writes `./autodev_plan_step_state.db` on a PostgreSQL URL — invisible to other replicas and to every backup manifest | `backend/plans/step_state.py:132`, absent from `backend/persistence/backup.py` | E50-S3 + E55 | High |
| G11 | 13 domain tables are created outside `MigrationRunner`, so none is in `schema_version`, none has a `down` path, and none has RLS | `quotas/store.py:78-118`, `secret_store/store.py:91`, `execution/policy.py:235-283`, `environments/store.py:126-155`, `plans/step_state.py:159`; zero matches in `migrations/postgres_versions.py` | E50 | High |
| G12 | The shipped `prod` Compose stack cannot run its own migrations — `CREATE EXTENSION vector` against stock `postgres:16-alpine` | `migrations/postgres_versions.py:253` vs `infrastructure/docker-compose.yml:116` | E48 | High |
| G13 | No PostgreSQL in CI — every PostgreSQL path is asserted against a monkeypatched `psycopg`, which is why G9-G12 stayed invisible | no `services:` block in `.github/workflows/`; `tests/unit/persistence/test_postgres_store.py:73-92` | E56 + E57 | High |

## 3. Files changed/created

Created:
- `docs/v2_platform/beta_gap_analysis.md` (this document)
- `docs/v2_platform/phases/e32_isolated_execution_beta.md`
- `docs/v2_platform/phases/e33_secrets_credential_governance.md`
- `docs/v2_platform/phases/e34_packaging_global_install.md`
- `docs/v2_platform/phases/e35_beta_readiness_gates.md`
- `docs/v2_platform/decisions/ADR-013-beta-isolation-backend.md` (Proposed)
- `docs/v2_platform/decisions/ADR-014-secret-store-format.md` (Proposed)
- `docs/v2_platform/decisions/ADR-015-global-install-strategy.md` (Proposed)

Edited:
- `docs/architecture/v2_platform_reference.md` (§18.9 v2.0-beta: adds
  criteria 10–12)
- `docs/v2_platform/phases/e14_real_execution_governance.md` (E32
  boundary; CLI UX vs E34)
- `docs/v2_platform/phases/e11_observability_security_multitenant.md`
  (E32/E33 audit sinks, additive)
- `docs/v2_platform/phases/e12_quality_evals.md` (contract tests
  `execution_environment`, `secret_backend`)
- `docs/v2_platform/phases/e28_execution_environments.md` (consumes the
  E32 contract; does not fork it)
- `docs/v2_platform/progress.md` (epic table + E32–E35 backlog)
- `docs/v2_platform/decisions/README.md` (ADR-013/014/015 index)
- `docs/feature_matrix.md` (E32–E35 rows)

## 4. New Epics Map (dependencies and priority)

| Epic | Wave | Depends on | Enables | Priority |
| --- | --- | --- | --- | --- |
| E32 — Isolated Execution Environment (Beta cut) | v2.0-beta | E14-S4, E0, E11 | E28 (v2.2), gate (10) | 1 |
| E33 — Secrets & Credential Governance | v2.0-beta | E11, E32, E0 | E14 with credentials, gate (11) | 2 |
| E34 — Packaging & Global Install | v2.0-beta | E14 (CLI), E33-S1, E8 | gate (12), upgrade GA (E13) | 3 |
| E35 — Beta Readiness: Gates & Runbooks | v2.0-beta | E32, E33, E34, E11, E12 | mechanical gate, GA readiness | 4 |

Sequencing: E32-S1 and E33-S1 can start in parallel (contracts);
E33-S2 depends on E32-S1; E34-S2 depends on E33-S1; E35 consolidates at
the end but E35-S1 (evidence map) can start as soon as the phase docs are
approved.

## 5. Beta Cut of the Isolated Environment × E14 × E28

- **E14** defines *what* executes (tasks, actions, permission/approval
  policy, governed autonomy) and the runner contract (E14-S4).
- **E32 (new, Beta)** defines *where* it executes: an environment
  abstraction with a pluggable backend, fail-closed network/filesystem
  policy, lifecycle, and audit. The backend choice is ADR-013 (pending) —
  Beta is implementable with the default backend behind the abstraction.
- **E28 (v2.2)** evolves the E32 contract: `trusted`/`untrusted` classes,
  microVM-class backends, and machine snapshots. E28-S2 **consumes** the
  E32 contract; it does not replace it. The provisioning time baseline
  measured in E32-S3 becomes the reference gain for E28-S1.

## 6. New Beta Gates (criteria added to §18.9 v2.0-beta)

- **(10)** Real execution occurs in a fail-closed isolated environment
  (E32): backend resolved by policy, typed denials, and class/profile
  recorded on every execution — proven by run records, not by
  configuration.
- **(11)** No secret in plaintext in prompts, logs, events, traces,
  diffs, or artifacts (E33): injection only inside the execution
  environment; a leak fixture that is redacted and audited.
- **(12)** Clean-environment install documented and verified (E34):
  `autodev` operational without a repository checkout, with a reported
  version and an upgrade between two versions that preserves data.

## 7. Open Decisions Register (E35-S3-T1, updated 2026-08-19)

None of the three decisions below remains open — all were resolved
**within the epic itself** that motivated them, not silently: each ADR
documents the decision and its consequences in its own file. This
register is kept regardless, as required by E35-S3-T1 — "no silent
resolution" means the decision must be traceable with options,
recommendation, owner, and date, and it is.

| Decision | ADR | Options | Recommendation | Owner | Decide by | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Beta isolation backend | [ADR-013](decisions/ADR-013-beta-isolation-backend.md) | container hardening; bubblewrap; gVisor; microVM | container hardening in Beta behind the abstraction; microVM in E28 | Epic owner (E32) | before E32-S2 | **Decided** — Accepted 2026-08-18, container hardening (`HardenedContainerBackend`) |
| Secret store format | [ADR-014](decisions/ADR-014-secret-store-format.md) | encrypted file; encrypted-at-rest DB; external KMS/vault | encrypted-at-rest DB as the self-host default; KMS as a pluggable backend | Epic owner (E33) | before E33-S2 | **Decided** — Accepted 2026-08-18, encrypted SQLite (Fernet) behind `SecretBackendKind` |
| Global install strategy | [ADR-015](decisions/ADR-015-global-install-strategy.md) | pipx/uv tool; container bundle; install script | pipx/uv for the CLI + bundle for self-host | Epic owner (E34) | before E34-S2 | **Decided** — Accepted 2026-08-18, hybrid pip/pipx/uv + docker-compose |

`docs/v2_platform/decisions/README.md` still listed the three as
"Proposed" at this point — corrected alongside this update (doc drift,
not a new decision).

## 7.1 Beta Risk Register (E35-S3-T2)

| Risk | Impact | Mitigation | Stories | Status |
| --- | --- | --- | --- | --- |
| Isolation escape | Untrusted code execution escapes the isolated environment, reaching the host or unauthorized network | Default-deny network/filesystem policy, decision audited per execution, `UnavailableBackend` as a configuration kill switch; the stronger microVM class is the target of E28 | E32-S2, E32-S4, E28 (v2.2) | Mitigated (Beta); additional defense-in-depth in E28 |
| Secret leak | Secret value exposed in a log, event, trace, diff, or artifact | Exact-value redaction before any persistence, applied inside `emit_event()` (protects every producer); the `secret.leak.suspected` event audits the attempt | E33-S2, E33-S3 | Mitigated; detection is exact-match only (no entropy heuristic — declared limitation) |
| Failed upgrade | Migration corrupts or loses data while updating between versions | Mandatory backup before migrating (`BackupManager`); `MigrationRunner` refuses a migration against a schema newer than the code knows (`SchemaVersionMismatchError`); rollback via documented restore | E34-S3, E8-S4 | Mitigated; no staging environment to rehearse the restore (open gap, §11 criterion 6) |
| Uncontrolled execution | A task consumes resources/budget beyond the expected amount, or runs indefinitely | Budgets that fail closed in the reasoning engine, per-category execution policy, per-tenant quotas, pending-decision timeout | E14-S2, E14-S3, E11-S3 | Mitigated |

Living register — reviewed at every wave boundary (end of v2.0-beta,
start of v2.1), or whenever a new material risk is identified.

## 8. Validation Commands Run

Documentation-only validations (MD-only scope):
- `grep -rn "E3[2-5]" docs/ --include='*.md'` — before: no occurrences;
  after: consistency across phase docs, progress, feature matrix, and §18.9.
- Verification of relative links cited in the new docs (see final
  verification Task in the diff).
- `git status` / `git diff --stat` — final diff for human review; no
  push, merge, or PR.

## 9. Plan Honesty Note

This plan does **not** claim coverage of "all SOTA concepts". It
prioritizes an honest, testable Beta: a complete core coding flow
(plan → code → patch → validate → evaluate) with provable isolation,
secrets, and install, and preserved extensibility (contracts + explicit
pending ADRs) without compromising security, predictability, or quality.

## 10. Gap Resolution Status (E35, 2026-08-19)

E32, E33, and E34 were implemented and merged into `main` (PRs #105,
#106, #107). This paragraph closes the audit cycle opened in Section 2,
without rewriting the historical record above.

| # | Gap | Status | How it was resolved |
| --- | --- | --- | --- |
| G1 | Beta gate does not require proven isolation | **Resolved** | §18.9 criterion (10) (fail-closed isolated execution, audited backend/profile); evidence in §11 below |
| G2 | E14×E28 boundary with no defined Beta cut | **Resolved** (already in E32) | `phases/e32_isolated_execution_beta.md` — relation to E14/E28 section |
| G3 | Secrets with no Beta epic | **Resolved** | §18.9 criterion (11) (scoped reference, redaction, audited leak fixture); evidence in §11 |
| G4 | Global install with no packaging/upgrade strategy | **Resolved** | §18.9 criterion (12) (`autodev --version`, clean install, upgrade with compatibility check); evidence in §11 |
| G5 | Gate criteria with no evidence map | **Resolved** | Section 11 below — evidence map for the 12 §18.9 v2.0-beta criteria, with honest status (Met/Partial/Open) |
| G6 | Negative paths outside the Beta acceptance definition | **Resolved** | `docs/v2_platform/beta_acceptance_flow.md` (E35-S2) |
| G7 | Architectural decisions with no ADR | **Resolved** | ADR-013/014/015 all **Accepted** (see updated Section 7, E35-S3) |
| G8 | Beta incident runbooks missing | **Resolved** | `docs/v2_platform/runbooks/e35_*.md` (E35-S3) |
| G9 | Four stores refuse the PostgreSQL URL `prod` mandates | **Open** | New 2026-08-21. Owned by E49 + E51-E54 |
| G10 | `plan_step_state` silently diverts to a stray SQLite file | **Open** | New 2026-08-21. Owned by E50-S3 + E55 |
| G11 | 13 tables outside `MigrationRunner`, unversioned and without RLS | **Open** | New 2026-08-21. Owned by E50 |
| G12 | Shipped `prod` Compose stack cannot run its own migrations | **Open** | New 2026-08-21. Owned by E48 |
| G13 | No PostgreSQL in CI; PostgreSQL asserted against fakes | **Open** | New 2026-08-21. Owned by E56 + E57 |

G1-G8 closed the E35 audit cycle on 2026-08-19 and remain closed. **G9-G13
are a second, later audit cycle**, opened 2026-08-21 by reading the `prod`
code path directly rather than the tracker, and recorded here rather than
rewriting the record above. They are tracked by the E48-E60 program
(`postgres_production_completeness.md`) and map to new gate criteria 13-15
in Section 11.

## 11. Gate Evidence Map (§18.9 v2.0-beta) — E35-S1-T2

Fact-vs-recommendation discipline (E35-S1-T3): **Met** requires citable
evidence (test, doc, execution record); **Partial** means real but
incomplete evidence against the criterion; **Open** means no evidence was
found — it is a named gap, not presumed resolved.

| # | Criterion (summary) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Real plan→code→patch→validate→evaluate flow with RBAC, fail-closed budgets, end-to-end traces | **Partial** | Each component has isolated evidence — RBAC (`backend/tests/unit/security/`, ADR-018), fail-closed budgets (E14-S2 `backend/execution/policy.py` + E11-S3 quotas), traces (`test_orchestrator_agent_step_emits_correlated_span`), real execution (E14-S1..S4). **No single composite test** covers the five steps within one execution — that is exactly the object of `docs/v2_platform/beta_acceptance_flow.md` (E35-S2), which is also not a new automated test, it is the executable checklist that composes this evidence. |
| 2 | Hybrid retrieval p95 < 300 ms and recall baseline | **Open** | `phases/e7_context_rag.md` line 178 already states: "unverified without a live [environment]". The harness exists (`backend/repository/retrieval/benchmark.py`, `scripts/benchmark_retrieval.py --max-p95-ms --min-recall`), but there is no recorded run against a live environment proving the target. |
| 3 | Run streaming starts < 1 s | **Open** | `backend/tests/unit/api/test_runs_stream_v2.py` covers functional correctness (backlog, resume, heartbeat, disconnection) but no test measures a numeric latency bound. |
| 4 | Every extension point has a green contract test; quality gates block merge | **Met** | `backend/tests/contract/test_extension_point_coverage.py`; `ci-backend.yml` (`lint-typecheck` + `patch-validation` gates, E12-S4) |
| 5 | UI WCAG 2.2 AA on key screens; flow editor with round-trip | **Partial** | Round-trip: `frontend/lib/flow/yaml.ts` + E17-S6 (**Met**). WCAG: per-component coverage via Storybook-axe in E15/E17 (`frontend/**/*.stories.tsx`), but **no consolidated per-screen WCAG 2.2 AA audit** exists — the E19 visual-parity audit (proposed, not planned) would be the natural vehicle for this. |
| 6 | Backup/restore validated (RPO ≤ 5 min, RTO ≤ 30 min) in staging | **Open** | `phases/e8_persistence_data.md` lines 203–205: "No staging environment" — validation done via a documented execution procedure (`runbooks/e8_restore_runbook.md`), not in real staging. |
| 7 | v2 design language + E15 app shell adopted | **Met** | E15 Done (4/4); `docs/v2_platform/phases/e15_design_language_shell.md` |
| 8 | `/v2` API parity (E16) | **Met** | E16 Done (4/4); `docs/v2_platform/phases/e16_redesign_api_enablement.md` |
| 9 | Control Center screens (E17) | **Met** | E17 Done (6/6); `docs/v2_platform/phases/e17_control_center_screens.md` |
| 10 | Isolated execution fail-closed by default, audited decision (E32) | **Met** | `backend/environments/` (`EnvironmentBackend`, `UnavailableBackend`), `environment.instance.*`/`environment.access.*` event catalog, `docs/environments/beta_isolation.md`, ADR-013 Accepted |
| 11 | No secret in cleartext; audited leak fixture (E33) | **Met** | `backend/secret_store/redaction.py`, `secret.leak.suspected` event, `docs/security/secrets.md`, ADR-014 Accepted |
| 12 | Clean-environment install verified; upgrade preserves data (E34) | **Met** | `scripts/verify_clean_install.sh`, `backend/ops/version.py`, `MigrationRunner.run_pending` (`SchemaVersionMismatchError`), `docs/execution/cli-install.md`, `docs/execution/upgrade.md`, ADR-015 Accepted |
| 13 | `prod` boots from empty on PostgreSQL 16 + pgvector and serves a real vector query | **Open** | `backend/persistence/migrations/postgres_versions.py:253` runs `CREATE EXTENSION IF NOT EXISTS vector`; `infrastructure/docker-compose.yml:116` ships stock `postgres:16-alpine`, which does not bundle it — PG migration 4 cannot succeed on the shipped stack. No recorded from-empty `prod` bring-up. Added 2026-08-21 (E48). |
| 14 | SQLite and PostgreSQL pass the same functional contract | **Open** | 13 tables have no PostgreSQL migration (zero matches in `postgres_versions.py`) and 5 stores refuse or divert on a PostgreSQL URL (G9, G10). No contract suite compares backends; `backend/sdk/testing.py:30` pins SQLite via the `DurableStore = SQLiteStore` alias (`persistence/database.py:23`). Added 2026-08-21 (E49-E56). |
| 15 | Every pull request runs a real `prod`-profile E2E | **Open** | No `services:` block in any workflow under `.github/workflows/`; `backend/tests/unit/persistence/test_postgres_store.py:73-92` monkeypatches `sys.modules["psycopg"]`. Mocked connections are not PostgreSQL evidence. Added 2026-08-21 (E57). |

**Honest summary**: 7 of 15 criteria **Met** (4, 7, 8, 9, 10, 11, 12), 2
**Partial** (1 and 5 — real but incomplete evidence), 6 **Open** (2, 3, 6,
13, 14, 15 — no verification evidence, only tooling/documentation to
verify). Criteria 13-15 were added 2026-08-21 by the E48-E60 PostgreSQL
Production Completeness program
(`postgres_production_completeness.md`); they correspond to gaps G9-G13
above and are named against verified file:line evidence, not presumed.
This is not the "complete" gate — it is
the **measurable** gate: each
remaining gap is named with its exact cause, not hidden behind
a checked box. Closing 2 and 6 requires a live environment (staging /
a populated retrieval dataset) that is out of scope for E35 (E35
audits and maps evidence; it does not own staging infrastructure).
