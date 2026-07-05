"""Reasoning Engine and Reasoning Strategy extension point (epic E4).

This package delivers the E4-S1 story: a typed, versioned contract for
pluggable reasoning strategies (:mod:`backend.reasoning.contract`), the
instrumented mediator that enforces budgets/guardrails/traces
(:mod:`backend.reasoning.engine`), the durable strategy registry
(:mod:`backend.reasoning.registry`), and the declarative reasoning policy
model (:mod:`backend.reasoning.policy`).

See ``docs/architecture/v2_platform_reference.md`` §8 for the full
specification and ``docs/reasoning/contract.md`` for the user-facing guide.
"""

from __future__ import annotations

from backend.reasoning.contract import (
    GUARDRAIL_ACTIONS,
    REASONING_CONTRACT_HOST_API,
    STOP_REASONS,
    Budget,
    BudgetExceededError,
    GuardrailBlockedError,
    GuardrailResult,
    LLMResult,
    ReasoningContext,
    ReasoningError,
    ReasoningInput,
    ReasoningOutput,
    ReasoningStrategy,
    ReasoningStrategyManifest,
    ToolResult,
    ToolSpec,
    TraceEvent,
    Usage,
    load_reasoning_strategy_manifest,
    validate_reasoning_strategy_manifest,
)
from backend.reasoning.engine import (
    GuardrailCheck,
    ReasoningEngine,
    ToolImplementation,
    budget_from_policy,
)
from backend.reasoning.policy import (
    DEFAULT_REASONING_POLICY_ID,
    GuardrailSpec,
    ReasoningBudgetPolicy,
    ReasoningPolicy,
    SelectionRule,
    SelectionSpec,
    TracingSpec,
    default_reasoning_policy,
    load_reasoning_policy,
    select_strategy,
    validate_reasoning_policy,
)
from backend.reasoning.registry import (
    PLATFORM_HOST_VERSION,
    ReasoningStrategyRegistry,
    is_host_compatible,
)
from backend.reasoning.selection import SelectionDecision, resolve_strategy
from backend.reasoning.service import ReasoningRunResult, ReasoningService
from backend.reasoning.agent_binding import (
    budget_from_agent_budgets,
    reasoning_input_from_agent,
)

__all__ = [
    "Budget",
    "BudgetExceededError",
    "DEFAULT_REASONING_POLICY_ID",
    "GUARDRAIL_ACTIONS",
    "GuardrailBlockedError",
    "GuardrailCheck",
    "GuardrailResult",
    "GuardrailSpec",
    "LLMResult",
    "PLATFORM_HOST_VERSION",
    "REASONING_CONTRACT_HOST_API",
    "ReasoningBudgetPolicy",
    "ReasoningContext",
    "ReasoningEngine",
    "ReasoningError",
    "ReasoningInput",
    "ReasoningOutput",
    "ReasoningPolicy",
    "ReasoningRunResult",
    "ReasoningService",
    "ReasoningStrategy",
    "ReasoningStrategyManifest",
    "ReasoningStrategyRegistry",
    "STOP_REASONS",
    "SelectionDecision",
    "SelectionRule",
    "SelectionSpec",
    "ToolImplementation",
    "ToolResult",
    "ToolSpec",
    "TraceEvent",
    "TracingSpec",
    "Usage",
    "budget_from_agent_budgets",
    "budget_from_policy",
    "default_reasoning_policy",
    "is_host_compatible",
    "reasoning_input_from_agent",
    "resolve_strategy",
    "load_reasoning_policy",
    "load_reasoning_strategy_manifest",
    "select_strategy",
    "validate_reasoning_policy",
    "validate_reasoning_strategy_manifest",
]
