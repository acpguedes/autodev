# AGENTS.md

Repository-wide guidance for autonomous coding agents contributing to AutoDev Architect.

## Mission-aware contribution rules

Contributors should treat this repository as the foundation of an open source, self-hostable GenAI software engineering platform.

When making changes:

- prioritize platform robustness over demo polish;
- prefer explicit workflows over hidden prompt behavior;
- prefer structured outputs over unstructured text for machine-driven actions;
- prefer minimal, reviewable patches;
- preserve or improve OSS/self-hosting viability;
- avoid choices that force dependence on paid infrastructure.

## Architectural priorities

Default priorities for new work:
1. persistence and durability;
2. workflow correctness;
3. repository intelligence;
4. patch and validation execution;
5. observability and governance;
6. UX improvements.

## Stack direction

Preferred stack choices for this repository:

- FastAPI for backend services.
- PostgreSQL as system of record.
- pgvector for semantic memory.
- Redis for queues/cache/locks.
- MinIO for artifacts.
- tree-sitter for code intelligence.
- Next.js for web UI.
- Docker for sandbox execution.
- Kubernetes for production deployment.
- OpenTelemetry + Prometheus + Grafana + Loki for observability.

Avoid introducing new infrastructure dependencies unless there is a clear architectural justification.

## Engineering rules

- Keep domain state outside prompt text where possible.
- Use typed schemas for API payloads and machine-readable agent outputs.
- Prefer asynchronous execution for long-running workflows.
- Do not hardcode product behavior that should be user-configurable or policy-driven.
- Do not implement broad rewrite behavior where patch-based changes are feasible.
- Keep local-model compatibility in mind when adding provider integrations.

## Documentation rules

When behavior, architecture, stack choices, or workflow semantics change, update the relevant docs:

- `README.md`
- `DESCRIPTION.md`
- `docs/architecture/*`
- `docs/implementation/*`
- `docs/roadmap.md`

## Contributor mindset

The project should grow into a serious OSS alternative in the AI software engineering space. Favor maintainability, transparency, and deployability over short-lived demos.

