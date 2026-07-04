# RFC-001: Plugin Extension-Point Catalog

- **Status:** Accepted
- **Author(s):** AutoDev Team          **Date:** 2026-07-04
- **Reviewers:** v2 platform maintainers
- **Epic(s):** E1                 **Stories:** E1-S1
- **Comment deadline:** 2026-07-04

## Summary

Adopt the canonical v2 plugin extension-point catalog and `plugin.yaml` contract used by
the Plugin Host. The catalog is: `agent`, `skill`, `tool`, `reasoning`, `router`,
`selector`, `evaluator`, `context_provider`, `retriever`, `validation_gate`,
`ui_panel`, and `event_handler`.

## Motivation

E1 is the prerequisite for agent, skill, reasoning, retrieval, validation, UI, and
event extensibility. A manifest that accepts unknown extension points would push
contract drift into runtime behavior, so the host must validate against a closed,
typed catalog before discovery or activation.

## Proposed design

The core publishes `backend.plugins.catalog` as the typed source of extension-point
kinds. `plugin.yaml` requires `schemaVersion`, `id`, `version`, `hostApi`, `runtime`,
and at least one `extensionPoints` entry. Plugin ids use `namespace/name` kebab-case,
plugin versions use SemVer, and `hostApi` uses ranges such as `>=2.0 <3.0`.

The validator fails closed with actionable reasons when required fields are missing,
ids or versions are malformed, permissions are unknown, or an extension point is not
in the catalog.

### Contracts and compatibility

- **API change:** none in E1-S1.
- **hostApi/SemVer change:** initial v2 plugin manifest contract, compatible with
  `hostApi: ">=2.0 <3.0"`.
- **Data migrations:** none.

## Alternatives considered

1. **Free-form extension point names** — rejected because it makes contract tests and
   activation compatibility unenforceable.
2. **Reuse v1 drop-a-file seams directly** — rejected because they lack manifests,
   `hostApi` ranges, permissions, and isolation.

## Impact

- **Security / RBAC / permissions:** unknown permission blocks are rejected; omitted
  permissions grant nothing.
- **Observability (traces/metrics/events):** later lifecycle stories emit plugin events
  against this catalog.
- **Cost / budgets / quotas:** no direct cost impact.
- **Accessibility (if UI):** UI extension points are declared but not mounted in E1-S1.
- **Performance / SLOs:** manifest validation target is < 50 ms.

## Implementation and rollout plan

1. Publish the catalog and manifest validator in the backend package.
2. Publish the JSON schema path and author documentation.
3. Make Plugin Host discovery consume this validator in E1-S2.

## Open questions

None for E1-S1. Additional extension kinds require a later RFC/ADR because they are
public contract changes.
