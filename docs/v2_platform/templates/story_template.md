# Story / Subtask Templates

> Source: `docs/architecture/v2_platform_reference.md`, §18.4 (machine-readable YAML form)
> and Appendix (J) (narrative Markdown form). Both describe the same unit of work
> (`E<n>-S<m>` or `E<n>-S<m>-T<k>`) at different altitudes:
>
> - Use the **YAML form** (§18.4) when the story needs to live as structured, diffable
>   backlog data (e.g. checked into a tracker, generated/consumed by tooling).
> - Use the **Markdown form** (Appendix J) when writing the human-facing ticket/PR
>   description.
>
> Every `E<n>-S<m>` MUST follow one of these templates. Fields are mandatory; "N/A" is
> only allowed with a justification. IDs use `namespace/name` kebab-case, versions use
> SemVer, event names use `domain.entity.action` in the past tense (repository-wide
> convention — see §7 of the reference doc and `docs/v2_platform/agent_guide.md`).

## YAML form (§18.4)

```yaml
# story: E<n>-S<m> — <short title>
id: E<n>-S<m>
epico: E<n>
titulo: <short, actionable title>

objetivo: |
  <1-3 sentences: what platform capability this delivers and why>

escopo:
  inclui:
    - <item in scope>
  nao_inclui:
    - <item out of scope>

criterios_aceite_funcionais:
  - id: AC-1
    given_when_then: "Given ... When ... Then ..."   # verifiable by test
  - id: AC-2
    given_when_then: "..."

criterios_nao_funcionais:
  - dimensao: latencia|cobertura|seguranca|a11y|budget|disponibilidade|escala
    alvo: <numeric value from the reference doc's global targets or story-specific>
    como_medir: <metric/dashboard/test>

dor_especifico:                # in addition to the global DoR (dor_checklist.md)
  - <story-specific precondition>

dod_especifico:                # in addition to the global DoD (dod_checklist.md)
  - <story-specific completion criterion>

dependencias:
  - <E<n>-S<m> or component>   # see the epic's dependency table for sequencing

riscos:
  - risco: <description>
    prob_impacto: <baixo|medio|alto>
    mitigacao: <action>

estimativa: <XS|S|M|L|XL>       # relative size, fits in one iteration

metricas_sucesso:
  - <measurable indicator of delivered value>

subtarefas:
  - id: E<n>-S<m>-T1
    desc: <executable technical step>
  - id: E<n>-S<m>-T2
    desc: <...>
```

## Markdown form (Appendix J)

```markdown
# <E<n>-S<m>[-T<k>]> — <Story or subtask title>

- **Type:** Story | Subtask
- **Epic:** E<n> — <epic name>
- **Parent:** <E<n>-S<m>> (if subtask)
- **Owner:** <name>            **State:** Backlog | Ready | In progress | In review | Done

## Description / value
<!-- As a <persona>, I want <capability> so that <benefit>. 1-2 paragraphs. -->

## Functional acceptance criteria
- [ ] Given <context>, when <action>, then <observable result>.
- [ ] <...>

## Non-functional criteria
- [ ] **Latency/Performance:** <e.g. p95 read endpoint < 300 ms>.
- [ ] **Security:** <RBAC, explicit permissions, sandbox, secrets>.
- [ ] **Observability:** <traces/metrics/events: domain.entity.action>.
- [ ] **Cost/Budgets:** <token/USD/time ceilings; tenant quotas>.
- [ ] **Accessibility (if UI):** WCAG 2.2 AA; keyboard navigation.
- [ ] **Data reliability (if applicable):** RPO <= 5 min, RTO <= 30 min.

## Definition of Ready (DoR)
- [ ] Scope and value clear; linked to the epic.
- [ ] Testable acceptance criteria defined.
- [ ] Affected contracts/schemas and events identified.
- [ ] Dependencies unblocked; ADR/RFC exists if needed.
<!-- Full checklist in dor_checklist.md. -->

## Definition of Done (DoD)
- [ ] Functional and non-functional criteria met.
- [ ] Tests + contract tests green; core coverage >= 85%.
- [ ] Evals/quality gates met; docs updated.
- [ ] Review approved; observability verified.
<!-- Full checklist in dod_checklist.md. -->

## Dependencies
- **Blocked by:** <E<n>-S<m>, plugin/service, decision>.
- **Blocks:** <dependent items>.
- **Canonical components touched:** <Control Plane API, Orchestration Engine, Plugin Host, ...>.

## Risks and assumptions
- **Risk:** <description> — **Probability/Impact:** <L/M/H> — **Mitigation:** <action>.
- **Assumption:** <what we're assuming to be true>.

## Estimate
- **Size:** <story points / t-shirt (S/M/L/XL)>.
- **Confidence:** <low | medium | high>.

## Success metrics
- <product/technical metric that validates the item, e.g. run success rate, p95 reduction, eval score >= threshold>.
```
