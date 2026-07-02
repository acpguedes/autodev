# ADR Template (Architecture Decision Record)

> Source: `docs/architecture/v2_platform_reference.md`, Appendix (F) and §19.3.
> Copy the block below into `docs/v2_platform/decisions/ADR-<NNN>-<slug>.md` and fill it in.
> ADRs are immutable once accepted: a later change is recorded as a **new** ADR that
> supersedes the previous one — never edit an accepted ADR in place except for its
> `Status` field.

**When an ADR is required (§19.3):** any change that causes a MAJOR version bump of a
platform artifact (core, plugin, agent, skill, flow, eval, API, event — see the SemVer
table in §19.1) requires an accepted RFC and a corresponding ADR. MINOR changes to
public contracts should still record a lightweight ADR.

```markdown
# ADR-<NNN>: <Short decision title>

- **Status:** Proposed | Accepted | Rejected | Superseded by ADR-<NNN> | Deprecated
- **Date:** YYYY-MM-DD
- **Authors:** <name(s)>
- **Related epic:** E<n>  <!-- reference the canonical epic list in phases/ -->
- **Supersedes/Relates to:** ADR-<NNN> (if applicable)

## Context
<!-- What is the problem? What forces (technical, product, cost, security) are at
     play? What constraints and non-functional requirements apply? -->

## Decision
<!-- What was decided? State it affirmatively and unambiguously. Align with the
     project's preferred stack decisions (OSS-first, PostgreSQL, Redis, pgvector,
     MinIO, tree-sitter, Docker, Next.js, FastAPI) when relevant. -->

## Alternatives considered
1. **<Alternative A>** — pros / cons / reason for rejection.
2. **<Alternative B>** — pros / cons / reason for rejection.

## Consequences
- **Positive:** <benefits, unlocked capabilities>
- **Negative / trade-offs:** <debt, risks, limits>
- **Contract impact:** <SemVer/hostApi bump, migrations, compatibility>

## Rollback plan
<!-- How would this be reverted if it turns out to be wrong? Is the migration reversible? -->

## References
- RFC-<NNN>, issues, benchmarks, relevant links.
```
