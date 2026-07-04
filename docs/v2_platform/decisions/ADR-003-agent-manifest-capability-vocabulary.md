# ADR-003: Agent Manifest and Initial Capability Vocabulary

- **Status:** Accepted
- **Date:** 2026-07-04
- **Authors:** AutoDev maintainers
- **Related epic:** E2-S1
- **Supersedes/Relates to:** ADR-002

## Context

E2 makes agents first-class plugins. The Agent Registry and Selector need a stable,
versioned vocabulary for matching work to agents without depending on Python class
names or prompt text. The vocabulary must be small enough for Alpha while covering the
existing v1 agents that will be migrated first.

## Decision

Adopt `agent.yaml` as the public Agent Manifest contract with `schemaVersion: "2.0"`,
`kind: Agent`, SemVer identity, `hostApi` compatibility, versioned capabilities,
strict IO schemas, explicit permissions, and fail-closed default budgets.

The initial capability vocabulary is:

| Capability | Version | Purpose |
| --- | --- | --- |
| `code.implementation` | `1.0.0` | Implement source changes and patch-oriented work. |
| `code.refactor` | `1.0.0` | Restructure code without intended behavior changes. |
| `planning.decompose` | `1.0.0` | Break a goal into ordered engineering steps. |
| `security.review` | `1.0.0` | Review changes for security and policy risks. |
| `validation.plan` | `1.0.0` | Produce validation steps and success criteria. |

Unknown capability ids fail manifest validation. Adding a new optional capability is
a minor contract change and should be recorded in a later ADR.

## Alternatives considered

1. **Free-form capability strings** - More flexible, but selectors cannot make stable
   routing decisions and plugin authors get no contract-test feedback.
2. **One capability per v1 class name** - Easy to migrate, but leaks implementation
   names and does not express reusable platform semantics.

## Consequences

- **Positive:** E2-S2 can implement deterministic capability search and version
  resolution on top of manifest data.
- **Negative / trade-offs:** Early third-party agents must use the Alpha vocabulary
  until new capabilities are accepted.
- **Contract impact:** Introduces the Agent Manifest and capability vocabulary as an
  experimental Alpha public contract under `hostApi: ">=2.0 <3.0"`.

## Rollback plan

If the vocabulary is too narrow, add new capability ids in a follow-up ADR and keep
existing ids valid through the `2.x` host API line.

## References

- `docs/architecture/v2_platform_reference.md` §6 and §18.6
- `docs/v2_platform/phases/e2_agent_framework.md`
