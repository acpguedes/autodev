# CLAUDE.md

Guidance for Claude-style assistants and similar AI contributors working in this repository.

## Primary intent
Help evolve AutoDev Architect into a strong open source, self-hostable AI software engineering platform.

## Repository priorities
When proposing changes, optimize for:

- explicit architecture;
- durable state;
- agent interoperability;
- patch-based workflows;
- validation execution;
- transparent docs;
- OSS-first stack choices.

## Preferred decisions
- PostgreSQL over ad hoc in-memory persistence.
- Redis for queue/cache/locks.
- pgvector before introducing a dedicated vector database.
- MinIO for artifacts.
- tree-sitter for code intelligence.
- Docker sandboxing for execution.
- Next.js for UI.
- FastAPI for backend control plane.

## Working style
- Use structured outputs and schemas where machine-readable data is needed.
- Keep user-visible summaries separate from control metadata.
- Favor changes that narrow the gap between product vision and implementation.
- If introducing a new subsystem, document why it belongs and what problem it solves.

## Execution environment
- ALWAYS activate the project virtualenv before running anything that depends on it:
  `source .venv/bin/activate`.
- Apply this to all executions — running the backend, tests, scripts, linters, migrations,
  and any `python`/`pip` invocation. Prefer `source .venv/bin/activate && <command>` so the
  command runs inside the venv.
- If `.venv` does not exist yet, create it first (`python -m venv .venv`), activate it, then
  install dependencies inside it.

## Planning vs. execution (Claude Code)
- For non-trivial tasks: produce the plan with Opus, then execute the implementation directly
  in Sonnet — do not hand off to Codex unless the user explicitly requests it.
- Only involve Codex (the `codex` / `codex:codex-rescue` agent or the Codex CLI runtime) when
  the user explicitly asks for a Codex handoff.
- Keep `AGENTS.md` aligned with this file so any handoff is consistent.

## Documentation expectation
For any meaningful architecture or behavior change, update documentation in the corresponding files under `docs/` and the project root.

## v2 platform refactor
The v2.0 platform rewrite (plugin core, agent framework, flow engine, and the rest of
the E0-E13 roadmap) is specified in `docs/architecture/v2_platform_reference.md` and
tracked in `docs/v2_platform/` (progress, per-epic phase docs, ADR/RFC log, and
templates). Read `docs/v2_platform/agent_guide.md` before picking up any `E<n>-S<m>`
story, and follow `docs/v2_platform/documentation_rebuild.md` when a wave (Alpha/Beta/
GA) exits — it supersedes ad hoc doc edits for that kind of change.

