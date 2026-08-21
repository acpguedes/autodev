# Roadmap

## North star

AutoDev Architect is an open source, self-hostable, patch-first GenAI engineering
platform with planning, repository intelligence, validation, approvals, and
observability.

> **The v2 platform is the product.** The v1 fixed linear pipeline (Navigator ->
> Analyzer -> Architect -> Coder -> DevOps -> Validator -> Responder) has been
> superseded by a plugin core with agents/flows/reasoning/routing/skills as
> versioned extension points, specified in
> [`docs/architecture/v2_platform_reference.md`](architecture/v2_platform_reference.md).
> v1 is frozen at the [`v1` release tag](https://github.com/acpguedes/autodev/releases/tag/v1)
> and its documentation is archived under
> [`docs/archive/v1/README.md`](archive/v1/README.md) as a design audit trail, not a
> description of current behavior.
>
> The v2.0-alpha and v2.0-beta waves are both complete; see
> [`docs/v2_platform/progress.md`](v2_platform/progress.md) for the live, authoritative
> tracker of epic/story status, wave-exit evidence, and what is genuinely still open.
> That file — not this one — is the place to check "where are we on the platform?"
>
> **Beta is not fully signed off.** Of the 12 v2.0-beta exit criteria, 9 are met or
> partially met and 3 remain honestly open: the hybrid-retrieval p95/recall benchmark
> has never been run against a live environment, run-streaming start latency has no
> numeric assertion (only functional correctness), and backup/restore has no staging
> environment to validate RPO/RTO against. See
> [`docs/v2_platform/progress.md`](v2_platform/progress.md) (Beta wave exit gates)
> and [`docs/v2_platform/beta_gap_analysis.md`](v2_platform/beta_gap_analysis.md) §11
> for the full evidence map. This roadmap will not describe Beta as done until those
> three gaps close.

---

## What's next

With Beta substantially complete, the near-term sequence is:

1. **GA (E13 - Marketplace & GA)** — verified plugin publish/install, Control Plane
   SLOs, production-proven RPO/RTO, the v1 -> v2 upgrade path, and the GA
   documentation rebuild. See
   [`phases/e13_marketplace_ga.md`](v2_platform/phases/e13_marketplace_ga.md).
2. **v2.1 - Spec-Driven Development & Agent Harness (E20-E25)** — spec core,
   compiler, executable verification, harness/loop engineering, and AI-assisted
   Spec Studio / Extension Studio.
3. **v2.2 - SOTA Integration (E26-E31)** — agent runtime context engineering,
   execution-grounded verification and test-time compute, execution
   environments/self-verification, durable learning and skill library, FinOps and
   autonomy governance, and the library spec registry.
4. **v2.3 - Platform Excellence (E36-E40)** — SDD operating model and document
   authority, context-independent harness/looping excellence, a SOTA evidence
   matrix and capability benchmark, product modes with agentic security and
   minimum FinOps, and architecture fitness functions with local-first
   degradation.

Each wave's epics, dependencies, and status are tracked in the epic table in
[`docs/v2_platform/progress.md`](v2_platform/progress.md).

---

## Delivered — additive multi-agent / skills / plans platform buildout (v1)

Before the v2 rewrite, a platform-wide buildout landed these subsystems **additively**
on the v1 pipeline, attached through plugin seams (auto-discovery of API routers,
agents, and CLI plugins — see
[`docs/archive/v1/plugin_seams.md`](archive/v1/plugin_seams.md)). All existing behavior
and tests were preserved; heavier capabilities were gated behind environment flags and
their optional dependencies were kept out of `backend/requirements.txt`. Mapping to the
legacy release goals below:

| Roadmap area | Delivered (additive) |
|---|---|
| 0.3 Repository intelligence | pluggable repo providers + optional tree-sitter symbol extraction; `GET /repository/symbols` |
| 0.4 / 0.8 Patch + validation | stdlib patch engine (dry-run by default; `AUTODEV_ENABLE_PATCH_APPLY`); flag-gated Docker/local validation sandbox (`AUTODEV_ENABLE_SANDBOX`); `/patches/*`, `/validation/*` + CLI |
| 0.5 Approval workflow + UI | persisted plan store with approval gates (`/plans/*` GET/PUT/approve/reject + CLI); frontend pages for skills/agents/plans/patches |
| 0.6 OSS competitive | CLI expanded (`skills`, `agents`, `plans`, `patches`, `validate`); backend + frontend CI workflows; first frontend unit tests (vitest) |
| 0.9 Observability | request-id tracing middleware + Prometheus `GET /metrics` (OTel used only if importable) |
| Multi-agent / skills | skills subsystem (registry + built-ins, `/skills` + CLI); specialized `security`/`refactor`/`docs` agents + registry (`/agents` + CLI); dynamic run-type routing/supervisor + opt-in `POST /chat/dynamic` (`AUTODEV_DYNAMIC_ORCH`) |
| Async groundwork | in-process job queue (optional Redis backend); `POST /jobs`, `GET /jobs/{id}` |

Subsystem docs (historical): [`skills_subsystem.md`](archive/v1/skills_subsystem.md),
[`dynamic_orchestration.md`](archive/v1/dynamic_orchestration.md),
[`patches_and_validation.md`](implementation/patches_and_validation.md).

**Deferred in v1, delivered by v2:** pgvector semantic memory, Kubernetes, full
Grafana/Loki dashboards, and dynamic orchestration as the default `/chat` path.
PostgreSQL persistence and MinIO artifacts landed in the v2 E0 foundations, and
OpenTelemetry/Prometheus/Grafana/Loki observability landed in v2 E11 — see
[`docs/v2_platform/progress.md`](v2_platform/progress.md).

---

## Legacy v1 release goals (Release 0.1 - 1.0)

These are the original v1 "Release 0.x/1.0" goals, kept for historical reference per
[`docs/v2_platform/documentation_rebuild.md`](v2_platform/documentation_rebuild.md)
("annotate the release entry pointing at `docs/v2_platform/progress.md` instead of
maintaining two parallel roadmaps"). Each entry below is annotated with the v2 epic
that superseded it; consult
[`docs/v2_platform/progress.md`](v2_platform/progress.md)'s epic table for current
status, not the goals/success-criteria lists here.

### Release 0.1 - Prototype foundation

> Superseded by v2 **E1** (Plugin Core & SDK) and **E2** (Agent Framework) — Done.

Focus: basic agent orchestration, initial API, chat demo UI, deterministic fallbacks.
Was largely present in the v1 repository; the orchestration and agent model it
prototyped has since been replaced end to end by the plugin/agent framework.

### Release 0.2 - Durable platform core

> Superseded by v2 **E0** (Foundations & Hardening — PostgreSQL state store, Redis
> queue/cache/locks) and **E3** (Orchestration Engine — run state machine) — both
> Done.

Goals were PostgreSQL persistence, Redis-backed background execution, a run state
machine, structured agent outputs, and improved API contracts. All delivered by the
v2 foundation and orchestration epics.

### Release 0.3 - Repository intelligence

> Superseded by v2 **E7** (Context & RAG) — Done.

Goals were tree-sitter indexing, lexical + semantic retrieval, symbol discovery, and
repository metadata storage. Note: the Beta wave's hybrid-retrieval p95/recall
benchmark against a live environment is still open (see the north-star callout
above and `phases/e7_context_rag.md`).

### Release 0.4 - Patch and validation pipeline

> Superseded by v2 **E14** (Real Task Execution & Governed Autonomy) and **E32**
> (Isolated Execution Environment) — both Done.

Goals were patch proposal generation, a patch application service, a Docker sandbox
runner, and an executable validator.

### Release 0.5 - Approval workflow and full UI

> Superseded by v2 **E14** (permission/approval policy), **E15-E18** (frontend
> redesign: design language, API enablement, Control Center screens, front door and
> run experience) — all Done.

Goals were plan approval, patch approval, run timeline UI, diff view UI, and an
artifact/validation explorer.

### Release 0.6 - OSS competitive platform

> Superseded by v2 **E34** (Packaging & Global Install, `autodev` CLI) and **E11**
> (Observability, Security & Multi-tenant) — both Done.

Goals were local model support as a first-class path, a CLI, self-hosting docs,
multi-repository policies, observability dashboards, and stronger CI/CD and testing.

### Release 0.7 - Governance and policy control plane

> Superseded by v2 **E11** (Observability, Security & Multi-tenant) and **E33**
> (Secrets & Credential Governance) — both Done.

Goals were persisted repository policy documents, approval rules by run type and
action category, command allowlists for validation/sandbox execution, audit events,
and workspace/repository switching with explicit active policy selection.

### Release 0.8 - Patch execution and sandbox validation

> Superseded by v2 **E14** and **E32** — both Done. See Release 0.4 above; these two
> legacy entries describe the same capability.

### Release 0.9 - Observability and operations

> Superseded by v2 **E11-S1** (Beta wave, complete 2026-08-15): correlated
> traces/metrics/logs, a self-hosted Collector/Prometheus/Tempo/Loki/Grafana stack,
> configurable sampling and retention, and a provisioned overview dashboard — see
> [`docs/ops/observability.md`](ops/observability.md). Alert delivery and
> operational runbooks landed in E11-S4.

Goals were OpenTelemetry instrumentation, Prometheus metrics for runs/agents/
validation outcomes, Grafana/Loki starter dashboards, operator-facing run
diagnostics in the UI, and CI coverage for backend, frontend, docs, and
infrastructure checks.

### Release 1.0 - Team-ready OSS platform

> Superseded by v2 **E0** (PostgreSQL/Redis/MinIO foundations, Done), **E11**
> (multi-tenant, Done), and **E13** (Marketplace & GA — Not started; this is the
> platform's current frontier, see "What's next" above).

Goals were a PostgreSQL + Redis production path replacing bootstrap-only storage
assumptions, multi-repository tenancy and policy inheritance, role-aware approvals
and artifact governance, documented production deployment on Docker Compose and
Kubernetes, and contributor/operator documentation for serious OSS adoption. The
storage and tenancy goals are delivered; GA-level SLO, production-proven backup/
restore, and the v1 -> v2 upgrade path remain open under E13.
