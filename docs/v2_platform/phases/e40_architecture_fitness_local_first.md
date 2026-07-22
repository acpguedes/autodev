# E40 — Architecture Fitness Functions & Local-First Degradation

**Wave:** v2.3 — Platform Excellence (some fitness functions should become Beta
quality gates as soon as their underlying contracts exist).
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E1-E14, E20-E23, E26-E30, E32-E35
**Enables:** continuous architectural integrity, self-hostable degradation,
and reduced erosion as the extension ecosystem grows.

## Objective

Protect the platform's architectural promises with executable fitness functions
and a local-first degradation matrix. Principles such as small core, typed
extension points, event append-only, API-first access, tenant isolation,
context quarantine, fail-closed budgets and secret redaction must be checked by
contracts, tests or ADR review instead of relying on contributor memory.

## Key result

Every release can report which architecture fitness functions are green,
waived or not applicable, and every optional capability declares how it behaves
in full, offline, single-model and degraded self-hosted modes.

## Stories

### E40-S1 — Architecture fitness-function catalog

Subtasks:
- `E40-S1-T1`: create `docs/architecture/fitness_functions.md` covering core
  size, extension boundaries, event catalog append-only, API-first, tenant
  isolation, immutable published specs/artifacts, no raw transcript handoff,
  fail-closed budgets, secrets redaction, sandbox fail-closed and plugin
  boundary/import restrictions.
- `E40-S1-T2`: classify each function by verification mechanism: static
  check, contract test, integration test, migration test, architecture review
  or ADR waiver.
- `E40-S1-T3`: link the catalog from E12 quality gates and the global DoD.

| Criterion | Detail |
| --- | --- |
| Functional | A reviewer can tell which check enforces each architectural principle |
| Non-functional | Fitness functions are additive and avoid new infrastructure dependencies |
| DoR (specific) | Existing principles and phase docs reviewed |
| DoD (specific) | Catalog linked from E12 and DoD checklist |
| Dependencies | E12 |

### E40-S2 — Local-first degradation matrix

Subtasks:
- `E40-S2-T1`: create `docs/architecture/local_first_degradation_matrix.md`
  for embeddings/vector store, LLM judge, oracle, marketplace, snapshots,
  browser runner, spec registry, SDD gates, code execution, eval reports and
  skills.
- `E40-S2-T2`: define modes: full, offline, single-model, no-Docker,
  no-vector-store and no-network.
- `E40-S2-T3`: define what may degrade, what must fail closed, and how UI/API
  reports degraded capability.

| Criterion | Detail |
| --- | --- |
| Functional | A self-hoster can predict behavior without hosted or paid infrastructure |
| Non-functional | No capability silently skips safety gates because an optional dependency is missing |
| DoR (specific) | E0/E11/E27/E28/E30 constraints reviewed |
| DoD (specific) | Matrix linked from architecture and relevant phase docs |
| Dependencies | E0, E11, E27, E28, E30 |

### E40-S3 — Fitness gate integration and waiver policy

Subtasks:
- `E40-S3-T1`: define how fitness checks run in CI, story validation and
  release readiness.
- `E40-S3-T2`: define waiver format with owner, expiry, risk and remediation
  story for checks that cannot yet be automated.
- `E40-S3-T3`: require release scorecards to show fitness status and active
  waivers.

| Criterion | Detail |
| --- | --- |
| Functional | A failed fitness function either blocks or has an explicit waiver with expiry |
| Non-functional | Manual waivers are auditable and trend toward automation |
| DoR (specific) | E40-S1 available |
| DoD (specific) | CI/release integration guidance documented |
| Dependencies | E40-S1, E38-S4 |

### E40-S4 — Contract drift and extension-ecosystem guardrails

Subtasks:
- `E40-S4-T1`: define drift checks for manifest schemas, extension-point
  contracts, event names and OpenAPI/MCP surfaces.
- `E40-S4-T2`: require marketplace/extension publishing to include fitness
  evidence for declared extension points.
- `E40-S4-T3`: define compatibility/deprecation review gates so extensions do
  not force core changes or paid infrastructure.

| Criterion | Detail |
| --- | --- |
| Functional | Extension ecosystem changes cannot silently break published contracts |
| Non-functional | SemVer and deprecation policy remain OSS-friendly |
| DoR (specific) | E1/E9/E13 contracts reviewed |
| DoD (specific) | Drift checks and publishing evidence requirements documented |
| Dependencies | E1, E9, E13 |

## Epic exit checklist

- [ ] All 4 stories meet the global DoD plus story-specific DoD above.
- [ ] Fitness catalog and degradation matrix are linked from architecture, E12 and release gates.
- [ ] `docs/v2_platform/progress.md` updated.
