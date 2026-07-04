# ADR-002: Plugin Manifest and Extension Catalog

- **Status:** Accepted
- **Date:** 2026-07-04
- **Authors:** AutoDev Team
- **Related epic:** E1
- **Supersedes/Relates to:** RFC-001

## Context

The v1 plugin seams auto-discover routers, CLI modules, and agents by importing files.
That pattern keeps changes additive, but it has no manifest, no host API compatibility
range, no permission declaration, no typed extension catalog, and no fail-closed
validation. E1 needs stable contracts so E2 agents can be packaged as plugins instead
of becoming new core internals.

## Decision

AutoDev v2 uses `plugin.yaml` as the required plugin descriptor. The backend publishes
a closed, typed extension-point catalog and refuses manifests that declare unknown
extension points. The minimum manifest fields are `schemaVersion`, `id`, `version`,
`hostApi`, `runtime.loader`, `runtime.entrypoint`, and at least one `extensionPoints`
item. Permissions are explicit and default-deny.

## Alternatives considered

1. **Adopt the v1 implicit discovery shape** — simple, but it cannot prove
   compatibility or permissions before import.
2. **Use a fully open manifest map** — flexible, but incompatible with SemVer-stable
   contract tests and Marketplace validation.

## Consequences

- **Positive:** E2/E6/E10/E13 can build on one manifest and catalog contract.
- **Negative / trade-offs:** every new extension kind now requires a small governance
  step instead of appearing organically.
- **Contract impact:** this is the initial v2 plugin manifest contract for host API
  `2.x`; later incompatible changes require a major contract bump.

## Rollback plan

The implementation is additive under `backend/plugins`. If the contract changes before
E2 consumes it, replace the catalog and schema in a follow-up ADR before enabling the
Plugin Host in production paths.

## References

- RFC-001
- `docs/architecture/v2_platform_reference.md` §5 and §18.6
