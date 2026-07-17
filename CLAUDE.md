# CLAUDE.md

Guidance for Claude-style assistants and similar AI contributors working in this repository.

## Primary intent
Help evolve AutoDev Architect into a strong open source, self-hostable AI software engineering platform.

## Repository priorities
When proposing changes, optimize for:

- API-first: every capability is exposed through the versioned Control Plane
  API (`/v2`) before or alongside any other surface. Web UI, CLI, and MCP are
  clients of that API and never touch the State Store or other internals
  directly (see `docs/architecture/v2_platform_reference.md` §2.13);
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
- Follow the Operational efficiency policy in AGENTS.md (binding): plan the
  full change set and apply it in the fewest safe passes; smallest sufficient
  verification with output reuse; delegate to subagents only when it shortens
  the critical path; stop once completion criteria are proven.

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

## Development workflow (binding)
`CONTRIBUTING.md` defines the mandatory workflow; in short:

- One branch per epic (`epic/e<N>-<slug>`, from `main`, pushed to origin) and one
  branch per story (`story/e<N>-s<M>-<slug>`, from the epic branch).
- On story completion: merge the story branch into the epic branch, push the epic
  branch, delete the story branch. On epic completion: merge to `main` **via PR only**.
- Every package, class, method, and function: English docstring (description, args,
  returns, raises) and complete type hints. All annotations and docs in English.
- Tests: story branches run only story-scoped tests (plus dependent areas when shared
  contracts are touched); the full suite (`make check`) gates the epic → `main` PR.
  Avoid unnecessary tests.

## Continuation & gap-closing shortcuts (binding)

These shortcuts define what to do when the user gives a terse continuation
instruction instead of naming a specific story/epic. Resolve them against
`docs/v2_platform/progress.md` (the canonical tracker) before writing code.

**"continue a implementação" / "execute a próxima etapa|fase|épico"
(or English equivalents):**
- Pick the next epic that makes sense in wave order: first any unfinished
  **Beta** epic (respecting the `Depends on` column); once Beta is complete,
  move to **v2.1**, then **v2.2**, in dependency order.
- Within the chosen epic, execute stories in order (S1 → Sn), honoring story
  dependencies and the branch workflow above.
- If two epics are equally eligible, prefer the one that unblocks the most
  downstream epics; state the choice and reasoning briefly before starting.

**"feche os gaps" / "execute stories abertos" (or similar):**
- Do NOT open a new epic. Find stories that are not implemented
  (`Not started`, or the missing part of a partial `x/y`) inside epics that
  have already been started/executed, and implement those, in dependency
  order.
- Cross-check the tracker against the code first: if a story is marked done
  but the code contradicts it, flag it; if code exists but the tracker is
  stale, update the tracker instead of re-implementing.

**Completion protocol (applies to both shortcuts).** When the requested
slice of work is finished and validated:
1. merge each story branch into the epic branch as it completes (per
   `CONTRIBUTING.md`) and delete the story branch;
2. open the PR from the epic branch to `main` (full suite `make check` must
   be green) — include the tracker/doc updates in the same PR;
3. merge (accept) that PR into `main`;
4. sync local and remote (`git checkout main && git pull`; make sure
   `origin` is up to date);
5. delete branches that are no longer needed (merged story/epic branches),
   both local and remote.

## Documentation expectation
For any meaningful architecture or behavior change, update documentation in the corresponding files under `docs/` and the project root.

## v2 platform refactor
The v2.0 platform rewrite (plugin core, agent framework, flow engine, and the rest of
the E0-E13 roadmap) is specified in `docs/architecture/v2_platform_reference.md` and
tracked in `docs/v2_platform/` (progress, per-epic phase docs, ADR/RFC log, and
templates). Read `docs/v2_platform/agent_guide.md` before picking up any `E<n>-S<m>`
story, and follow `docs/v2_platform/documentation_rebuild.md` when a wave (Alpha/Beta/
GA) exits — it supersedes ad hoc doc edits for that kind of change.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
