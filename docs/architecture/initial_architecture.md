# AutoDev Architect – Initial Architecture Decisions

This document consolidates the early agreements for the AutoDev Architect platform. The goal is to give every contributor a shared mental model before iterating on features.

## High-level Goals

- Deliver an LLM-orchestrated workflow capable of planning, coding and validating software changes.
- Keep human approval in the loop with transparent plans and diff previews.
- Provide modular agents so that future models or heuristics can be swapped without rewriting the orchestrator.

## System Decomposition

| Area | Purpose | Initial Decision |
| --- | --- | --- |
| Backend Orchestrator | Coordinate Planner → Navigator/Analyzer → Architect → Coder → DevOps → Validator | Python 3.11 + FastAPI service with in-memory session store. |
| Agent Implementations | Encapsulate behaviour per specialty | Shared `AgentContext`/`AgentResult` contracts. Stubs provide deterministic output for early integration tests. |
| Frontend Chat UI | Surface plans, agent responses and diffs | Next.js 14 application with React Server Components, styled layout, and REST calls to backend. |
| Infrastructure | Make it easy to run locally and in CI | Docker image for backend, docker-compose for local orchestration, GitHub Actions for testing, Terraform placeholders for cloud rollout. |
| Validation | Guarantee continuous feedback | Pytest suite covering orchestrator, hooks for future lint/unit integration. |

## Data Flow Overview

1. User submits a goal through the chat UI.
2. Backend `PlannerAgent` produces a list of steps; the orchestrator stores them in the session state.
3. Each user prompt triggers sequential agent execution following the configured order (Navigator → Analyzer → Architect → Coder → DevOps → Validator).
4. Results are persisted in memory per session and returned to the frontend for rendering.
5. Validator feedback will later be used to refine plans or request rework from other agents.

## Interfaces and Contracts

- **AgentContext**: carries session id, goal, conversation history, and arbitrary artifacts so agents can share structured metadata.
- **AgentResult**: returns human-readable content plus metadata for downstream consumers (e.g., coder tasks, CI instructions).
- **Orchestrator API**: exposes `/plan` to bootstrap sessions and `/chat` to execute agent chains.

## Open Questions and Next Steps

- Persisting sessions across restarts (Redis/Postgres) once deterministic prototypes stabilize.
- Adding repository indexing (Tree-sitter + vector DB) to replace the placeholder Navigator implementation.
- Implementing patch generation and automated validation triggered by the Validator agent.
- Expanding Terraform definitions to stand up the full production environment.

These decisions will evolve as the product matures; contributors should treat this document as the canonical reference for the current sprint and propose updates via pull requests.
