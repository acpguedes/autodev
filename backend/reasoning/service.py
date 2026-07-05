"""Reasoning service: policy-driven selection, execution, and fallback (E4-S4).

Ties the strategy registry, the policy selector, and the Reasoning Engine
together: it resolves the strategy for a run (recording the decision in the
trace), executes it, and — when the run ends ``budget_exhausted`` and the policy
declares ``on_exceed: degrade_to:<strategy>`` — retries once with the fallback
strategy. The default (``fail_closed``) simply returns the exhausted result.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from backend.reasoning.contract import ReasoningInput, ReasoningOutput, TraceEvent
from backend.reasoning.engine import GuardrailCheck, ReasoningEngine, ToolImplementation
from backend.reasoning.registry import ReasoningStrategyRegistry
from backend.reasoning.selection import SelectionDecision, resolve_strategy
from backend.agents.provider import LLMProvider

_DEGRADE_PREFIX = "degrade_to:"


@dataclass(frozen=True)
class ReasoningRunResult:
    """Outcome of a policy-driven reasoning run.

    Attributes:
        output: The final :class:`ReasoningOutput` (after any fallback).
        decision: The strategy selection decision that started the run.
        degraded_to: The fallback strategy id if a degrade occurred, else ``None``.
    """

    output: ReasoningOutput
    decision: SelectionDecision
    degraded_to: str | None = None


class ReasoningService:
    """Selects, runs, and (on budget overrun) degrades reasoning strategies."""

    def __init__(
        self,
        registry: ReasoningStrategyRegistry,
        *,
        provider: LLMProvider | None = None,
        guardrail_checks: Mapping[str, GuardrailCheck] | None = None,
        tool_impls: Mapping[str, ToolImplementation] | None = None,
        tenant_id: str = "local",
        on_event: Callable[[TraceEvent], None] | None = None,
    ) -> None:
        """Initialize the service with a registry and Engine configuration.

        Args:
            registry: Registry the selected/fallback strategies are resolved from.
            provider: LLM provider for the Engine; defaults to the offline stub.
            guardrail_checks: Guardrail id to predicate mapping for the Engine.
            tool_impls: Tool name to implementation mapping for the Engine.
            tenant_id: Tenant runs are scoped to.
            on_event: Trace sink; receives selection/degrade decisions and every
                Engine trace event.
        """
        self._registry = registry
        self._on_event = on_event
        self._engine = ReasoningEngine(
            provider=provider,
            guardrail_checks=guardrail_checks,
            tool_impls=tool_impls,
            tenant_id=tenant_id,
            on_event=on_event,
        )

    async def run(
        self,
        run_input: ReasoningInput,
        *,
        context: Mapping[str, Any] | None = None,
        manifest_strategy: str | None = None,
        node_override: str | None = None,
        selector_choice: str | None = None,
    ) -> ReasoningRunResult:
        """Resolve a strategy, run it, and apply the policy's overrun fallback.

        Args:
            run_input: Immutable run input (carries the policy and budget).
            context: Signals matched against the policy's selection rules.
            manifest_strategy: Agent Manifest strategy declaration, if any.
            node_override: Flow Node strategy override, if any.
            selector_choice: Dynamic Selector choice (E5), if any.

        Returns:
            The :class:`ReasoningRunResult` with the final output and decision.
        """
        decision = resolve_strategy(
            run_input.policy,
            context=context,
            manifest_strategy=manifest_strategy,
            node_override=node_override,
            selector_choice=selector_choice,
        )
        self._emit("reasoning.selection.decided", {"strategy": decision.strategy_id, "source": decision.source})
        output = await self._engine.run(self._registry.resolve(decision.strategy_id), run_input)

        degraded_to: str | None = None
        if output.stop_reason == "budget_exhausted":
            fallback_id = _degrade_target(run_input.policy.budget.on_exceed)
            if (
                fallback_id
                and fallback_id != decision.strategy_id
                and fallback_id in self._registry.list_ids()
            ):
                self._emit(
                    "reasoning.selection.degraded",
                    {"from": decision.strategy_id, "to": fallback_id},
                )
                output = await self._engine.run(self._registry.resolve(fallback_id), run_input)
                degraded_to = fallback_id
        return ReasoningRunResult(output=output, decision=decision, degraded_to=degraded_to)

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        """Emit a service-level decision event to the trace sink, if configured.

        Args:
            name: Dotted event name.
            payload: Structured payload for the event.
        """
        if self._on_event is not None:
            self._on_event(TraceEvent(sequence=-1, name=name, payload=payload, timestamp=time.time()))


def _degrade_target(on_exceed: str) -> str | None:
    """Extract the fallback strategy id from an ``on_exceed`` directive.

    Args:
        on_exceed: The policy budget's ``on_exceed`` value.

    Returns:
        The fallback strategy id for ``"degrade_to:<id>"``, else ``None``.
    """
    if isinstance(on_exceed, str) and on_exceed.startswith(_DEGRADE_PREFIX):
        return on_exceed[len(_DEGRADE_PREFIX):].strip() or None
    return None


__all__ = ["ReasoningRunResult", "ReasoningService"]
