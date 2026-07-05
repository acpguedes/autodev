# ADR-007 — Reasoning Engine Boundary and Enforcement Model

- **Status:** Accepted
- **Epic:** E4-S1
- **Date:** 2026-07-05
- **Related:** RFC-003 (contract surface), reference §8

## Context

E4 introduces the **Reasoning Engine** and the `reasoning.strategy` extension
point (reference §8). Three boundary questions had to be settled before
implementation: (1) whether the contract surface is synchronous or asynchronous;
(2) how budgets, guardrails, and traces are enforced relative to the strategy;
and (3) which budget model reasoning uses.

Reference §8.3 illustrates the contract with `async def`. The v2 implementation
to date — Agent Runtime (E2), Flow Engine (E3), LLM providers — is entirely
synchronous; only FastAPI/Starlette middleware is async.

## Decision

1. **Async contract, synchronous host.** `ReasoningStrategy.run` and the
   `ReasoningContext` methods (`call_llm`, `call_tool`, `check_budget`, `verify`)
   are `async`, matching reference §8.3. The Engine `await`s the strategy; the
   underlying `LLMProvider` stays synchronous and is called directly inside the
   async mediator. Where the synchronous Agent Runtime hosts the Engine (E4-S4),
   the bridge is a localized `asyncio.run`. Rationale: fidelity to the reference
   and headroom for genuinely concurrent tool/branch fan-out in Debate/ToT
   (E4-S3) without a later breaking (MAJOR) contract change.

2. **Effects flow only through the mediator.** Strategies never touch a provider
   or tool directly. The Engine's `_Mediator` is the sole `ReasoningContext`
   implementation; it debits the `Budget` on every `call_llm`/`call_tool`,
   evaluates guardrails via `verify`, and records an ordered `TraceEvent` stream.
   The `on_event` sink is the Event Bus hook (E9) and the observability channel
   for a running strategy.

3. **Fail-closed budgets, engine-owned.** `check_budget` runs before every costly
   effect and raises `BudgetExceededError` once any dimension (tokens, cost,
   wall-clock, steps) is reached — **no external effect occurs past the ceiling**
   and the run terminates with `stop_reason="budget_exhausted"`. The Engine, not
   the strategy, is the budget authority (reference §8.4). Guardrail `block`
   yields `guardrail_blocked`; `repair_once` gives the strategy one in-run repair
   window (unrepaired at the Engine boundary ⇒ `guardrail_blocked`); `warn`
   records the violation and proceeds.

4. **Budget model.** Reasoning uses a single-`tokens` `Budget` (reference §8.4),
   distinct from `AgentBudgets` (which splits input/output tokens).
   `budget_from_policy` derives a run budget from a policy; the run > agent >
   policy precedence is applied by the caller at the Agent Runtime boundary
   (E4-S4).

## Consequences

- (+) Contract matches the reference; concurrent fan-out is expressible later
  without a breaking change.
- (+) Statelessness + mediated effects + an ordered trace make runs replayable
  (reference §8.6), reusing the ADR-005 determinism posture.
- (−) A sync→async bridge (`asyncio.run`) is required wherever the synchronous
  Agent Runtime hosts the Engine (E4-S4); it is documented and localized.
- (−) Async code is new to the backend outside middleware; tests drive it with
  `asyncio.run` to avoid adding an async test-framework dependency.
- Contract tests (`backend/tests/test_reasoning_contract.py`) gate every strategy
  implementation against this boundary.
