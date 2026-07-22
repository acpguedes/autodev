# E39 — Product Modes, Agentic Security & Minimum FinOps

**Wave:** v2.3 — Platform Excellence (security/FinOps minimums should be pulled
left into Beta stories before broad autonomous execution ships).
**Status:** Not started · **Stories:** 0/5 complete
**Depends on:** E11, E14, E23, E27, E30, E32, E33
**Enables:** clear competitive UX modes, safer MCP/plugin/tool execution, and
cost-aware autonomy before long-running loops are broadly available.

## Objective

Bind architectural capabilities to product modes and governance. Users should
understand whether they are chatting with a repo, planning, coding, launching a
background issue-to-PR agent, racing candidates, verifying UI, or authoring an
extension. Each mode must declare autonomy level, permissions, harness pattern,
security controls and budget policy.

## Key result

Every autonomous product surface has an explicit contract for inputs, outputs,
state, permissions, evidence, FinOps limits and threat controls. No high-cost or
high-risk loop can run without a pre-run estimate, budget hierarchy and kill
switch.

## Stories

### E39-S1 — Product mode contracts

Subtasks:
- `E39-S1-T1`: create `docs/product/v2_product_modes.md` with contracts for
  chat-with-repo, plan mode, code mode, issue-to-PR/background agent,
  multi-candidate race, UI/browser verification and extension authoring.
- `E39-S1-T2`: for each mode define input, output, spec requirement, harness
  pattern, permission defaults, gates, evidence and UX obligations.
- `E39-S1-T3`: update E14/E17/E18/E23/E24/E25/E28 docs to reference product
  modes instead of inventing surface-specific behavior.

| Criterion | Detail |
| --- | --- |
| Functional | A UI/API/CLI surface can name its product mode and inherit default policy |
| Non-functional | Modes preserve OSS/self-hosted viability and do not require vendor services |
| DoR (specific) | E14 and E23 contracts reviewed |
| DoD (specific) | Product mode doc linked from relevant phase docs |
| Dependencies | E14, E23 |

### E39-S2 — Agentic threat model

Subtasks:
- `E39-S2-T1`: create `docs/security/agentic_threat_model.md` covering prompt
  injection, malicious MCP/tool/plugin, exfiltration, cross-tenant leakage,
  secrets in context/artifacts, supply chain, reward hacking and browser
  automation attacks.
- `E39-S2-T2`: map each threat to preventive controls, detection signals,
  evidence, negative tests and owning epic.
- `E39-S2-T3`: make marketplace publishing, MCP enablement and autonomous
  execution reference the threat model.

| Criterion | Detail |
| --- | --- |
| Functional | Each risky extension/execution surface has documented mitigations and tests |
| Non-functional | Controls are fail-closed and do not assume a hosted control plane |
| DoR (specific) | E11/E32/E33 scopes reviewed |
| DoD (specific) | Threat model linked from security and relevant phase docs |
| Dependencies | E11, E13, E14, E32, E33 |

### E39-S3 — Minimum FinOps contract before autonomous loops

Subtasks:
- `E39-S3-T1`: define pre-run estimates for actions, harness loops,
  candidate races, browser verification and oracle review.
- `E39-S3-T2`: enforce budget hierarchy: tenant → project → run → phase →
  iteration → candidate, with kill switches at tenant/project/run levels.
- `E39-S3-T3`: add DoR requirements for E23-S2/E23-S4/E27-S1 so autonomous
  loops cannot start before minimum FinOps controls exist.

| Criterion | Detail |
| --- | --- |
| Functional | A candidate race or long-running harness cannot overspend its parent budget |
| Non-functional | Single-model/local installs get conservative defaults and explicit degradation messaging |
| DoR (specific) | ADR-006 and E30 reviewed |
| DoD (specific) | Minimum FinOps contract linked from E14/E23/E27/E30 |
| Dependencies | E14, E23, E27, E30 |

### E39-S4 — Autonomy policy profiles

Subtasks:
- `E39-S4-T1`: define policy profiles: `observe`, `suggest`, `approval`,
  `hybrid`, `autonomous_low_risk`, `autonomous_guarded`.
- `E39-S4-T2`: map product modes and harness patterns to default profiles and
  escalation triggers.
- `E39-S4-T3`: require human-readable and API-visible explanations when a mode
  downgrades autonomy due to budget, threat, missing sandbox or missing specs.

| Criterion | Detail |
| --- | --- |
| Functional | Operators can predict which actions require approval and why |
| Non-functional | Policy downgrade is explicit, never silent |
| DoR (specific) | E14 policy engine scoped |
| DoD (specific) | Autonomy profiles documented and cross-linked |
| Dependencies | E14, E32, E39-S1 |

### E39-S5 — Evidence-centered trust surface

Subtasks:
- `E39-S5-T1`: define evidence bundle requirements by product mode: plan,
  spec trace, diffs, tests, logs, screenshots/recordings, verifier verdicts,
  cost and security decisions.
- `E39-S5-T2`: require comments/review without stopping safe background work
  where mode policy permits.
- `E39-S5-T3`: ensure evidence bundles are redacted, tenant-scoped and linked
  to run/harness records for replay.

| Criterion | Detail |
| --- | --- |
| Functional | Reviewers see why work is trustworthy without reading raw agent transcripts |
| Non-functional | Evidence bundles avoid secrets and unbounded logs |
| DoR (specific) | E22-S5 and E28-S3 evidence contracts reviewed |
| DoD (specific) | Evidence requirements linked from product modes and verification docs |
| Dependencies | E22, E28, E33 |

## Epic exit checklist

- [ ] All 5 stories meet the global DoD plus story-specific DoD above.
- [ ] Product mode, threat model and minimum FinOps docs are linked from affected phase docs.
- [ ] `docs/v2_platform/progress.md` updated.
