# v1 architecture archive

This directory holds the documentation of the **v1 architecture**, frozen at the
[`v1` release](https://github.com/acpguedes/autodev/releases/tag/v1) and superseded by
the v2 platform. These files are kept as the project's **design audit trail** — the
record of what was decided and why, before the v2 rewrite. They are **not maintained**
and must not be treated as a description of current behaviour.

For what the platform does today, start at [`README.md`](../../../README.md),
[`docs/feature_matrix.md`](../../feature_matrix.md), and
[`docs/v2_platform/progress.md`](../../v2_platform/progress.md).

## What v1 was

v1 was a **fixed linear agent pipeline**:

```
Navigator -> Analyzer -> Architect -> Coder -> DevOps -> Validator -> Responder
```

Every run walked the same seven stages in the same order. Extending the system meant
editing the pipeline. Capabilities were bolted on through three auto-discovery "seams"
in `backend/api/main.py`, `backend/orchestrator/service.py`, and `backend/cli.py`.

v2 **inverts** that: a small core surrounded by typed **extension points** — plugins,
agents, flows, reasoning strategies, routing/selection policies, and skills — each
inhabited by versioned, manifest-declared extensions. The pipeline is no longer a fixed
shape; it is a `flow.yaml` executed by the Flow Engine.

## v1 -> v2 map

| Archived document | What replaced it |
| --- | --- |
| [`initial_architecture.md`](initial_architecture.md) | [`v2_platform_reference.md`](../../architecture/v2_platform_reference.md) — the design authority |
| [`target_architecture.md`](target_architecture.md) | [`v2_platform_reference.md`](../../architecture/v2_platform_reference.md) §4 (High-Level Architecture) |
| [`stack_decisions.md`](stack_decisions.md) | [`v2_platform_reference.md`](../../architecture/v2_platform_reference.md) §4 + [`ops/storage.md`](../../ops/storage.md), [`ops/observability.md`](../../ops/observability.md) |
| [`plugin_seams.md`](plugin_seams.md) | E1 Plugin Host + `plugin.yaml` — [`plugins/manifest.md`](../../plugins/manifest.md), [`plugins/permissions.md`](../../plugins/permissions.md), [`plugins/registry.md`](../../plugins/registry.md) |
| [`agent_spec.md`](agent_spec.md) | E2 `agent.yaml` + Agent Runtime — [`agents/manifest.md`](../../agents/manifest.md), [`agents/runtime.md`](../../agents/runtime.md), [`agents/registry.md`](../../agents/registry.md) |
| [`dynamic_orchestration.md`](dynamic_orchestration.md) | E3 Flow Engine + E5 Router/Selector — [`flows/spec.md`](../../flows/spec.md), [`flows/engine.md`](../../flows/engine.md), [`routing/contract.md`](../../routing/contract.md) |
| [`skills_subsystem.md`](skills_subsystem.md) | E6 `skill.yaml` + Skill Registry — [`skills/manifest.md`](../../skills/manifest.md) |
| [`data_model.md`](data_model.md) | E8 multi-tenant model + migrations — [`v2_platform_reference.md`](../../architecture/v2_platform_reference.md) §13 |
| [`mvp_refactor_plan.md`](mvp_refactor_plan.md) | [`v2_platform/progress.md`](../../v2_platform/progress.md) — its open units were subsumed by the v2 epics |
| [`implementation_strategy.md`](implementation_strategy.md) | [`v2_platform/progress.md`](../../v2_platform/progress.md) |

## Not archived

Some pre-v2 documents describe behaviour that is **still current** and therefore stay in
place, updated rather than frozen:

- [`docs/architecture/weaknesses_and_strategies.md`](../../architecture/weaknesses_and_strategies.md) — a living debt log, checked off per epic.
- [`docs/implementation/patches_and_validation.md`](../../implementation/patches_and_validation.md) — still the reference for patch/sandbox environment flags.
- [`docs/implementation/self_hosting_oss.md`](../../implementation/self_hosting_oss.md) — the self-hosting guide.
- [`docs/agents/agent-coder-v1-baseline.md`](../../agents/agent-coder-v1-baseline.md) — the v1 coder baseline is still shipped and referenced by the agent-coder plugin.
