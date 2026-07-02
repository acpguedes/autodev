# E13 — Marketplace & GA

**Wave:** GA
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E1, E12-S2, E11-S4, E0-E12 (all epics)
**Enables:** v2.0 General Availability
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.7.7 (E13), §18.8, §18.9

## Objective

Deliver plugin publication/installation, package **signing/verification**, and the
conditions for **v2.0 GA (General Availability)**.

## Key result

The community publishes and installs versioned, verified plugins/agents/skills; the
platform reaches the defined GA SLOs and criteria.

## Stories

### E13-S1 — Marketplace publication and catalog

Subtasks:
- `E13-S1-T1`: publication flow (packaging, metadata, SemVer version).
- `E13-S1-T2`: searchable catalog of plugins/agents/skills.
- `E13-S1-T3`: `hostApi` compatibility and deprecation policy.

| Item | Content |
| --- | --- |
| CF | Author publishes a versioned package; user discovers it via search/filters; declared and validated compatibility |
| CNF | Consistent metadata; scalable catalog; green contract test at publication time |
| DoR | E1 (SDK/manifest) and E12-S2 (contract tests) ready |
| DoD | End-to-end publication tested; catalog online; publication docs |
| Dependencies | E1, E12-S2 |

### E13-S2 — Installation, isolation, and lifecycle

Subtasks:
- `E13-S2-T1`: install/update/remove via the Plugin Host with explicit permissions.
- `E13-S2-T2`: dependency and version-range resolution.
- `E13-S2-T3`: install rollback and plugin quarantine.

| Item | Content |
| --- | --- |
| CF | Installs/updates/removes an isolated plugin; resolves dependencies; rollback available |
| CNF | Least privilege; a failing plugin does not affect the core; idempotent operation |
| DoR | E1 (Plugin Host) mature; E13-S1 ready |
| DoD | Lifecycle tested; quarantine verified; docs |
| Dependencies | E1, E13-S1 |

### E13-S3 — Package signing and verification

Subtasks:
- `E13-S3-T1`: cryptographic package signing and install-time verification.
- `E13-S3-T2`: chain of trust and trusted-publisher policies.
- `E13-S3-T3`: integrity and provenance verification (SBOM).

| Item | Content |
| --- | --- |
| CF | An unsigned/tampered package is refused; provenance is verifiable; trust policies are enforceable |
| CNF | Verification mandatory in production; SBOM available; installation audit |
| DoR | E13-S2 ready; trust model approved (ADR) |
| DoD | Tampered-package rejection tested; SBOM emitted; Marketplace security docs |
| Dependencies | E13-S2, E11-S4 |

### E13-S4 — GA criteria and readiness

Subtasks:
- `E13-S4-T1`: GA checklist (SLOs, security, docs, backups, evals).
- `E13-S4-T2`: load testing and verification of global non-functional targets (reference doc §6).
- `E13-S4-T3`: final hardening, upgrade migration, release notes.

| Item | Content |
| --- | --- |
| CF | Every GA checklist item met; upgrade from v1 documented; release notes published |
| CNF | Control Plane SLO 99.9%; read p95 < 300 ms; RPO <= 5 min/RTO <= 30 min under load test |
| DoR | E0-E12 complete and beta-stable; load environment available |
| DoD | GA checklist signed off; load test approved; GA release published |
| Dependencies | E0-E12 |

## v1 precursor / starting point

- Nothing exists today: there is no packaging, signing, catalog, or GA-readiness
  process. E13 is the final wave and is gated on every other epic reaching Beta
  completion — see the dependency graph in `docs/architecture/v2_platform_reference.md`
  §18.8.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [ ] Signed-package installation and verification (signature + SBOM) tested end to end.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] GA wave exit criteria satisfied per §18.9: verified plugin publish/install
      end-to-end; Control Plane SLO 99.9% and read p95 < 300 ms under load
      (>= 100 concurrent runs per reference node); RPO <= 5 min / RTO <= 30 min proven
      in production; GA checklist signed off; v1->v2 upgrade path documented and
      tested; GA release published with notes.
- [ ] `docs/v2_platform/documentation_rebuild.md` executed for the GA milestone (full
      documentation tree rebuild, including splitting `v2_platform_reference.md` into
      the permanent stable docs set).
