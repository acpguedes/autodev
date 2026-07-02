# RFC Template (Request for Comments)

> Source: `docs/architecture/v2_platform_reference.md`, Appendix (G) and §19.3.
> Copy the block below into `docs/v2_platform/decisions/RFC-<NNN>-<slug>.md` and fill it in.

**When an RFC is required (§19.3):** before any change affecting extension-point
contracts, `/v2` APIs, events, the data model, or security policy — i.e. anything that
would cause a MAJOR bump per the SemVer table in §19.1. Cycle: `Draft → Under review →
Accepted/Rejected → Implemented`. An accepted RFC references the impacted epic(s) and
the stories it produces, and is followed by an ADR (`adr_template.md`) once the
decision is fixed.

```markdown
# RFC-<NNN>: <Proposal title>

- **Status:** Draft | Under review | Accepted | Rejected | Deferred
- **Author(s):** <name(s)>          **Date:** YYYY-MM-DD
- **Reviewers:** <names/teams>
- **Epic(s):** E<n>                 **Stories:** E<n>-S<m> (if applicable)
- **Comment deadline:** YYYY-MM-DD

## Summary
<!-- One paragraph: what changes and why. -->

## Motivation
<!-- Problem, evidence, who is affected. Which guiding principle does this serve? -->

## Proposed design
<!-- Detailed description. Include contracts/schemas, affected canonical components
     (Control Plane API, Orchestration Engine, Plugin Host, ...), events
     (domain.entity.action) and manifest changes where relevant. -->

### Contracts and compatibility
- **API change:** <`/v2` endpoints, schemaVersion>
- **hostApi/SemVer change:** <MAJOR/MINOR/PATCH and impact on plugins>
- **Data migrations:** <versioned, reversible?>

## Alternatives considered
<!-- Options discarded and why. -->

## Impact
- **Security / RBAC / permissions:** <...>
- **Observability (traces/metrics/events):** <...>
- **Cost / budgets / quotas:** <...>
- **Accessibility (if UI):** WCAG 2.2 AA <...>
- **Performance / SLOs:** <p95, availability>

## Implementation and rollout plan
<!-- Phases, feature flags, migration strategy, GA. -->

## Open questions
<!-- Points that need a decision from the community/reviewers. -->
```
