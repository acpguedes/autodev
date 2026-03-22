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

## Documentation expectation
For any meaningful architecture or behavior change, update documentation in the corresponding files under `docs/` and the project root.

