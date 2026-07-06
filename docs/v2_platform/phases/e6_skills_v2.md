# E6 — Skills v2

**Wave:** Beta
**Status:** Done · **Stories:** 5/5 complete
**Depends on:** E1
**Enables:** E9-S4 (MCP) and composition in flows
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.6 (E6), §18.8, §18.9

## Objective

Redefine skills with a **Skill Manifest**, a **Skill Registry**, composition, and
**skills-as-plugin**, reusable by agents and flows.

## Key result

A `skill.yaml` publishes a skill (deterministic or LLM-assisted) with IO/permissions/
triggers; it is discovered, composed, and invoked by agents/flows under least
privilege.

## Stories

### E6-S1 — `skill.yaml` specification

Subtasks:
- `E6-S1-T1`: schema (id, version, IO, permissions, dependencies, triggers).
- `E6-S1-T2`: validation.
- `E6-S1-T3`: versioning.

| Criterion | Detail |
| --- | --- |
| Functional | Skill declares IO/permissions/triggers; IO outside the schema is rejected; deterministic vs. LLM-assisted are distinguished |
| Non-functional | Validation < 20 ms; contract tests per skill |
| DoR (specific) | Skill permission model defined |
| DoD (specific) | Schema in the SDK; `docs/skills/manifest.md` |
| Dependencies | E1-S1 |

### E6-S2 — Skill Registry (registration/discovery/versioning)

Subtasks:
- `E6-S2-T1`: persistence.
- `E6-S2-T2`: search by trigger/capability.
- `E6-S2-T3`: SemVer resolution.

| Criterion | Detail |
| --- | --- |
| Functional | Skills discovered by trigger/name; versions coexist; deprecation signaled |
| Non-functional | Search p95 < 100 ms; consistent with the Plugin Host |
| DoR (specific) | Query contract defined |
| DoD (specific) | `/v2` catalog endpoint; resolution test |
| Dependencies | E6-S1, E1-S5 |

### E6-S3 — Least-privilege invocation via the Agent Runtime

Subtasks:
- `E6-S3-T1`: invocation broker.
- `E6-S3-T2`: permission/budget enforcement.
- `E6-S3-T3`: call trace.

| Criterion | Detail |
| --- | --- |
| Functional | Agent/flow invokes a granted skill; a missing permission blocks it; the result returns within the schema |
| Non-functional | Least privilege (fail closed); skill budget applied; trace per invocation |
| DoR (specific) | Invocation contract defined |
| DoD (specific) | Denial-by-permission test; cost metrics |
| Dependencies | E6-S1, E2-S4, E1-S3 |

### E6-S4 — Skill composition

Subtasks:
- `E6-S4-T1`: skill chaining/pipelines.
- `E6-S4-T2`: dependency resolution between skills.
- `E6-S4-T3`: budget/error propagation.

| Criterion | Detail |
| --- | --- |
| Functional | Skills compose into a pipeline; a missing dependency is reported; an error stops execution with clean state |
| Non-functional | Aggregated budget fails closed; composition traced end-to-end |
| DoR (specific) | Composition semantics defined |
| DoD (specific) | Pipeline test and missing-dependency test |
| Dependencies | E6-S3 |

### E6-S5 — Reference skills as plugins

Subtasks:
- `E6-S5-T1`: deterministic skill (e.g. apply Patch with path-guard/dry-run).
- `E6-S5-T2`: LLM-assisted skill.
- `E6-S5-T3`: SDK examples.

| Criterion | Detail |
| --- | --- |
| Functional | The Patch skill applies a diff with path guard and dry-run; the LLM skill respects guardrails; both installable |
| Non-functional | Dry-run has no side effects; coverage >= 85% |
| DoR (specific) | Reference patch cases defined |
| DoD (specific) | Parity suite; runnable SDK examples |
| Dependencies | E6-S3, E1-S4 |

## v1 precursor / starting point

- A skills subsystem already exists and is `default`: a registry with auto-discovery
  (`backend/skills/registry.py`), built-in deterministic skills (`summarize_diff`,
  `extract_symbols_lexical`, `render_checklist`), `GET/POST /skills` endpoints, and a
  CLI — documented in `docs/implementation/skills_subsystem.md`. This is the direct
  precursor to E6-S1/E6-S2/E6-S5, but skills currently register via explicit import
  rather than a `skill.yaml` manifest, and have **no versioning, no declared
  permissions, no triggers, and no composition/pipeline model** — the gaps E6-S1
  through E6-S4 close.

## Epic exit checklist

- [x] All 5 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [x] Contract tests green for the skill IO/invocation extension points.
- [x] `docs/v2_platform/progress.md` updated.
- [x] Beta wave entry item "Skills v2" satisfied (§18.9).
