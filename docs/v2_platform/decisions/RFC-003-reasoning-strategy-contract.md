# RFC-003 — Reasoning Strategy Contract (`reasoning.strategy`)

- **Status:** Accepted
- **Epic:** E4-S1
- **Date:** 2026-07-05
- **Related:** ADR-007 (engine boundary), reference §8

## Summary

Defines the typed, SemVer-versioned contract a **Reasoning Strategy** implements
to plug into the **Reasoning Engine** at the `reasoning.strategy` extension
point, the `reasoning-strategy.yaml` manifest that packages a strategy as a
plugin (E1), and the `reasoning-policy.yaml` document that governs strategy
selection, budgets, guardrails, and tracing.

## Motivation

Reference §8 requires the Reasoning Engine to run *any* strategy that satisfies a
stable contract, with no strategy-specific code in the core. Reference strategies
(ReAct, Plan-and-Execute, Reflection, Debate/ToT, native tool-calling) ship as
first-party plugins and third parties add more without a core redeploy. That
requires a versioned, testable contract surface — this RFC.

## Contract surface (`backend/reasoning/contract.py`)

- **Data types:** `ReasoningInput` (task, messages, tools, budget, policy, seed),
  `ReasoningOutput` (content, `stop_reason`, usage, trace_id), `Usage` (immutable
  accumulator), `Budget` (tokens/cost_usd/wall_clock_ms/max_steps), `ToolSpec`,
  `LLMResult`, `ToolResult`, `TraceEvent`, `GuardrailResult`.
- **Protocols:** `ReasoningContext` (the mediator — `call_llm`, `call_tool`,
  `check_budget`, `verify`, `emit`) and `ReasoningStrategy` (`id`, `version`,
  `host_api`, `config_schema`, `run`).
- **Errors:** `ReasoningError`, `BudgetExceededError`, `GuardrailBlockedError`.
- **Manifest:** `ReasoningStrategyManifest` (`schemaVersion`, `kind`, `id`,
  `version`, `hostApi`, `entrypoint`) with published schema
  `reasoning-strategy.schema.json`.
- **Policy:** `ReasoningPolicy` (`selection`, `budget`, `guardrails`, `tracing`)
  with published schema `reasoning-policy.schema.json`.
- **Versioning:** `REASONING_CONTRACT_HOST_API = ">=2.0 <3.0"`; the SDK contract
  export (`backend/sdk/contracts.py`) is bumped to `1.2.0`.

## Contract rules

1. Every external effect flows through `ReasoningContext`; a strategy never calls
   a provider or tool directly.
2. A strategy is stateless between runs — state lives in the trace/run state.
3. `ctx.check_budget()` is called before each costly step (the Engine also checks
   before every mediated effect as a fail-closed backstop).
4. The final output passes `ctx.verify()` (guardrails) before being returned.

Contract tests (`backend/tests/test_reasoning_contract.py`) validate any
implementation against these rules; they are mandatory for the extension point
(E12).

## Rejected alternatives

- **Sync-only contract** — rejected for fidelity to reference §8.3 and to allow
  genuinely concurrent fan-out in Debate/ToT (E4-S3) without a later MAJOR bump.
  See ADR-007.
- **Reuse `AgentBudgets` verbatim** — rejected; reasoning uses the reference's
  single-`tokens` budget. The run > agent > policy precedence is applied at the
  Agent Runtime boundary (E4-S4) via `budget_from_policy`.

## Rollout

E4-S1 lands the contract, Engine, registry, policy model, published schemas, and
contract tests. E4-S2/S3 add first-party strategies; E4-S4 adds policy-driven
selection and Agent Runtime wiring.
