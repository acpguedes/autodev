# Definition of Ready (DoR) Checklists

> Source: `docs/architecture/v2_platform_reference.md`, §18.2 (global DoR) and Appendix (H).

## Global DoR (§18.2)

A Story only enters **Ready** (Gate G1, see §18.1) once **all** of the following are true:

- [ ] **Objective and value** described in 1-3 sentences, tied to the parent epic's key result.
- [ ] **Scope and non-scope** made explicit (what is in and what is out).
- [ ] **Functional acceptance criteria** written in a verifiable form (Given/When/Then or a testable list).
- [ ] **Applicable non-functional criteria** cited with a numeric target (latency, coverage, budget, a11y).
- [ ] **Affected contracts** identified (extension point, IO schema, event, `/v2` endpoint) with a `hostApi` range where applicable.
- [ ] **Dependencies** mapped (preceding stories/epics) and unblocked or mockable.
- [ ] **Data/fixtures** and required environment available (local SQLite, stub provider, seeds).
- [ ] **Known risks** listed with an initial mitigation.
- [ ] **Estimate** recorded (relative size) and fits in one iteration.
- [ ] **Success metrics** defined (what will be measured to declare value delivered).
- [ ] **Security/RBAC/tenant impact** assessed (least privilege, plugin permissions, isolation).

## Per-item DoR checklist (Appendix H)

Copy this block into a story/subtask before moving it into execution. Mark inapplicable
items N/A with a justification.

```markdown
# Definition of Ready (DoR) — <Story/Subtask ID: E<n>-S<m>[-T<k>]>

## Clarity and scope
- [ ] Objective and value described in 1-2 sentences, unambiguous.
- [ ] Scope delimited (what is in, what is out).
- [ ] Linked to the correct epic (E0-E13) and parent story.

## Criteria and contracts
- [ ] Functional acceptance criteria defined and testable.
- [ ] Applicable non-functional requirements identified (latency, security, cost, a11y).
- [ ] Affected contracts/schemas identified (io schema, /v2 schemaVersion, hostApi/SemVer).
- [ ] Impacted events named (domain.entity.action).

## Dependencies and technical readiness
- [ ] Dependencies (stories, plugins, services) identified and unblocked.
- [ ] Required data/environment/secrets available (or a plan to provide them).
- [ ] Required ADR/RFC exists (or the decision is recorded) when there is architectural impact.

## Risks and estimate
- [ ] Risks and assumptions listed, with initial mitigation.
- [ ] Estimate agreed by the team.
- [ ] Success metrics defined (how we'll know it worked).
```
