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

Preferred stack choices for this repository (status as of E0–E2 completion, 2026-07-04):

- FastAPI for backend services — **in place**.
- PostgreSQL as system of record — **landed (E0-S3)**, selected via `DATABASE_URL`.
- pgvector for semantic memory — planned.
- Redis for queues/cache/locks — **landed (E0-S6)**, optional backend.
- MinIO for artifacts — **landed (E0-S6)**, local store by default.
- tree-sitter for code intelligence — still a stub (see `docs/feature_matrix.md`).
- Next.js for web UI — **in place**.
- Docker for sandbox execution — flag-gated v1 sandbox; hardening tracked in E11.
- Kubernetes for production deployment — planned.
- OpenTelemetry + Prometheus — **landed (E0-S4)**; Grafana + Loki — planned.

Avoid introducing new infrastructure dependencies unless there is a clear architectural justification.

## Execution environment

- ALWAYS activate the project virtualenv before running anything that depends on it:
  `source .venv/bin/activate`.
- This applies to every execution: backend, tests, scripts, linters, migrations, and any
  `python`/`pip` command. Prefer `source .venv/bin/activate && <command>`.
- If `.venv` is missing, create it (`python -m venv .venv`), activate it, then install
  dependencies inside it.

## Engineering rules

- Keep domain state outside prompt text where possible.
- Use typed schemas for API payloads and machine-readable agent outputs.
- Prefer asynchronous execution for long-running workflows.
- Do not hardcode product behavior that should be user-configurable or policy-driven.
- Do not implement broad rewrite behavior where patch-based changes are feasible.
- Keep local-model compatibility in mind when adding provider integrations.

## Development workflow (binding)

`CONTRIBUTING.md` is the canonical workflow definition. Key rules:

- One branch per epic (`epic/e<N>-<slug>`, cut from `main`, pushed to origin); one
  branch per story (`story/e<N>-s<M>-<slug>`, cut from the epic branch).
- Story done: merge into the epic branch, push it, delete the story branch.
  Epic done: merge to `main` **via pull request only**, then delete the epic branch.
- Docstrings (English, Google style — description, args, returns, raises) and complete
  type hints on every package, class, method, and function. All annotations and
  documentation in English.
- Story branches run only story-scoped tests (plus dependent areas when a shared
  contract is touched); the epic → `main` PR requires the full suite green
  (`make check` / `make container-check`). Do not add unnecessary tests.

## Documentation rules

When behavior, architecture, stack choices, or workflow semantics change, update the relevant docs:

- `README.md`
- `DESCRIPTION.md`
- `docs/architecture/*`
- `docs/implementation/*`
- `docs/roadmap.md`

## v2 platform refactor

The v2.0 platform rewrite — inverting the fixed v1 pipeline into a plugin core
with agents/flows/reasoning/routing/skills/context as typed extension points — is
specified in `docs/architecture/v2_platform_reference.md` and tracked epic-by-epic in
`docs/v2_platform/` (see `docs/v2_platform/README.md` for an index). **Status: E0
(foundations), E1 (plugin core & SDK), and E2 (agent framework) are complete; E3+
have not started** — `docs/v2_platform/progress.md` is authoritative. Before starting
work on any `E<n>-S<m>` story, read `docs/v2_platform/agent_guide.md`. When a wave
(Alpha/Beta/GA) exits, follow `docs/v2_platform/documentation_rebuild.md` to bring the
rest of this documentation tree back in sync, rather than patching individual files
ad hoc.

## Contributor mindset

The project should grow into a serious OSS alternative in the AI software engineering space. Favor maintainability, transparency, and deployability over short-lived demos.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
