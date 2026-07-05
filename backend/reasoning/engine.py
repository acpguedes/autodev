"""Reasoning Engine: the instrumented mediator that runs a strategy (E4-S1).

The :class:`ReasoningEngine` executes a :class:`~backend.reasoning.contract.ReasoningStrategy`
through a mediator (:class:`_Mediator`) that is the single path for every LLM
call, tool call, guardrail check, and trace event. Budgets are enforced by the
Engine (never the strategy) and fail closed: once any budget dimension is
reached, no further external effect occurs and the run terminates with
``stop_reason="budget_exhausted"``. See ``docs/architecture/v2_platform_reference.md``
§8.1-§8.6 for the canonical specification.

The surface is synchronous-hosted but ``async`` at the contract boundary
(ADR-007): the Engine ``await``s a strategy's coroutine, while the underlying
:class:`~backend.agents.provider.LLMProvider` remains synchronous.
"""

from __future__ import annotations

import inspect
import time
import uuid
from dataclasses import replace
from typing import Any, Callable, Mapping, Sequence

from backend.agents.provider import LLMProvider, StubLLMProvider
from backend.reasoning.contract import (
    STOP_REASONS,
    Budget,
    BudgetExceededError,
    GuardrailBlockedError,
    GuardrailResult,
    LLMResult,
    ReasoningError,
    ReasoningInput,
    ReasoningOutput,
    ReasoningStrategy,
    ToolResult,
    ToolSpec,
    TraceEvent,
    Usage,
)
from backend.reasoning.policy import ReasoningPolicy

#: A guardrail check maps a candidate output to ``True`` when it passes.
GuardrailCheck = Callable[[Any], bool]

#: A tool implementation receives the call arguments and returns a result value.
ToolImplementation = Callable[[Mapping[str, Any]], Any]


class _Mediator:
    """Per-run implementation of :class:`~backend.reasoning.contract.ReasoningContext`.

    Tracks resource usage against the run budget, mediates every LLM and tool
    call, evaluates guardrails, and records an ordered trace. All budget
    enforcement is fail-closed: :meth:`check_budget` (called before each costly
    effect) raises :class:`BudgetExceededError` once any dimension is reached.
    """

    def __init__(
        self,
        *,
        budget: Budget,
        policy: ReasoningPolicy,
        provider: LLMProvider,
        tools: Sequence[ToolSpec],
        guardrail_checks: Mapping[str, GuardrailCheck],
        tool_impls: Mapping[str, ToolImplementation],
        run_id: str,
        tenant_id: str,
        strategy_id: str,
        clock: Callable[[], float],
        record_prompts: bool,
        on_event: Callable[[TraceEvent], None] | None = None,
    ) -> None:
        """Initialize the mediator for a single reasoning run.

        Args:
            budget: Resource ceiling enforced for the run.
            policy: Reasoning policy in force (guardrails, tracing).
            provider: LLM provider used to service ``call_llm``.
            tools: Tool specs available to the strategy this run.
            guardrail_checks: Guardrail id to predicate mapping (``True`` passes).
            tool_impls: Tool name to implementation callable mapping.
            run_id: Identifier of the run.
            tenant_id: Tenant the run is scoped to.
            strategy_id: Identifier of the strategy being executed.
            clock: Monotonic clock function, injectable for deterministic tests.
            record_prompts: Whether prompts/args are recorded in trace payloads.
        """
        self._budget = budget
        self._policy = policy
        self._provider = provider
        self._tools = {spec.name: spec for spec in tools}
        self._guardrail_checks = dict(guardrail_checks)
        self._tool_impls = dict(tool_impls)
        self._run_id = run_id
        self._tenant_id = tenant_id
        self._strategy_id = strategy_id
        self._clock = clock
        self._record_prompts = record_prompts
        self._on_event = on_event
        self._start = clock()
        self._usage = Usage()
        self._events: list[TraceEvent] = []
        self._seq = 0

    @property
    def usage(self) -> Usage:
        """Return the usage accumulated so far in the run."""
        return replace(self._usage, wall_clock_ms=self._elapsed_ms())

    @property
    def events(self) -> list[TraceEvent]:
        """Return a copy of the ordered trace events emitted so far."""
        return list(self._events)

    def _elapsed_ms(self) -> int:
        """Return milliseconds elapsed since the run started."""
        return int((self._clock() - self._start) * 1000)

    def _next_seq(self) -> int:
        """Return the next monotonically increasing trace sequence number."""
        seq = self._seq
        self._seq += 1
        return seq

    def emit(self, event: TraceEvent) -> None:
        """Record a trace event, stamping the authoritative sequence number.

        The caller's ``sequence`` is ignored: the Engine owns ordering so the
        trace is deterministically replayable regardless of the strategy.

        Args:
            event: The trace event to record.
        """
        self._append(replace(event, sequence=self._next_seq()))

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        """Build and record an internal trace event.

        Args:
            name: Dotted event name, e.g. ``"reasoning.llm.called"``.
            payload: Structured, redaction-aware payload for the event.
        """
        self._append(
            TraceEvent(sequence=self._next_seq(), name=name, payload=payload, timestamp=time.time())
        )

    def _append(self, event: TraceEvent) -> None:
        """Append an event to the trace and notify the event sink, if any.

        Args:
            event: The fully-stamped trace event to record.
        """
        self._events.append(event)
        if self._on_event is not None:
            self._on_event(event)

    async def check_budget(self) -> None:
        """Refresh wall-clock usage and raise if any budget is reached.

        Raises:
            BudgetExceededError: If any budget dimension has been reached; the
                accumulated :class:`Usage` is attached to the error.
        """
        current = replace(self._usage, wall_clock_ms=self._elapsed_ms())
        self._usage = current
        if current.exceeds(self._budget):
            self._emit("reasoning.budget.exhausted", {"usage": _usage_payload(current)})
            raise BudgetExceededError("budget_exhausted", current)

    async def call_llm(self, messages: Sequence[Mapping[str, Any]], **opts: Any) -> LLMResult:
        """Complete a prompt via the mediated provider, debiting the budget.

        Args:
            messages: Role-tagged messages to render into a prompt.
            **opts: Provider options (currently unused by the stub provider).

        Returns:
            The provider's result with token/cost accounting.

        Raises:
            BudgetExceededError: If the budget is already reached (no call made).
        """
        await self.check_budget()
        prompt = _render_prompt(messages)
        response = self._provider.complete(
            prompt,
            agent_id=self._strategy_id,
            run_id=self._run_id,
            tenant_id=self._tenant_id,
        )
        result = LLMResult(
            content=response.text,
            tokens_input=response.tokens_input,
            tokens_output=response.tokens_output,
            cost_usd=response.cost_usd,
        )
        self._usage = self._usage.accumulate(
            tokens=result.tokens_input + result.tokens_output,
            cost_usd=result.cost_usd,
            steps=1,
        )
        self._emit(
            "reasoning.llm.called",
            {
                "tokens": result.tokens_input + result.tokens_output,
                "cost_usd": result.cost_usd,
                "prompt": prompt if self._record_prompts else None,
            },
        )
        return result

    async def call_tool(self, name: str, args: Mapping[str, Any]) -> ToolResult:
        """Invoke a granted tool through the mediator, debiting the budget.

        Args:
            name: Identifier of the tool to invoke.
            args: Arguments matching the tool's schema.

        Returns:
            The tool's result.

        Raises:
            BudgetExceededError: If the budget is already reached (no call made).
            ReasoningError: If the tool is not available to this run.
        """
        await self.check_budget()
        if name not in self._tools:
            raise ReasoningError(f"tool not available to this run: {name}")
        impl = self._tool_impls.get(name)
        output = impl(dict(args)) if impl is not None else None
        result = ToolResult(name=name, output=output)
        self._usage = self._usage.accumulate(steps=1)
        self._emit(
            "reasoning.tool.called",
            {"name": name, "args": dict(args) if self._record_prompts else None},
        )
        return result

    async def verify(self, output: Any) -> GuardrailResult:
        """Evaluate configured guardrails against a candidate output.

        Args:
            output: Candidate output to verify.

        Returns:
            The first failing :class:`GuardrailResult`, or a passing result if
            every configured guardrail (with a registered check) passed.
        """
        for spec in self._policy.guardrails:
            check = self._guardrail_checks.get(spec.id)
            if check is None:
                continue
            passed = bool(check(output))
            self._emit(
                "reasoning.guardrail.evaluated",
                {"guardrail": spec.id, "passed": passed, "action": spec.on_violation},
            )
            if not passed:
                return GuardrailResult(
                    guardrail_id=spec.id,
                    passed=False,
                    action=spec.on_violation,
                    message=f"guardrail '{spec.id}' violated",
                )
        return GuardrailResult(guardrail_id="", passed=True)


class ReasoningEngine:
    """Executes reasoning strategies under fail-closed budgets and guardrails."""

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        guardrail_checks: Mapping[str, GuardrailCheck] | None = None,
        tool_impls: Mapping[str, ToolImplementation] | None = None,
        tenant_id: str = "local",
        clock: Callable[[], float] = time.monotonic,
        on_event: Callable[[TraceEvent], None] | None = None,
    ) -> None:
        """Initialize the engine with a provider and optional guardrails/tools.

        Args:
            provider: LLM provider; defaults to the offline :class:`StubLLMProvider`.
            guardrail_checks: Guardrail id to predicate mapping shared by runs.
            tool_impls: Tool name to implementation mapping shared by runs.
            tenant_id: Tenant runs are scoped to by default.
            clock: Monotonic clock function, injectable for deterministic tests.
        """
        self._provider = provider or StubLLMProvider()
        self._guardrail_checks = dict(guardrail_checks or {})
        self._tool_impls = dict(tool_impls or {})
        self._tenant_id = tenant_id
        self._clock = clock
        self._on_event = on_event

    async def run(self, strategy: ReasoningStrategy, input: ReasoningInput) -> ReasoningOutput:
        """Execute a strategy for one run and return its final output.

        The Engine aggregates authoritative usage from the mediator, validates
        the terminal ``stop_reason``, and applies the fail-closed budget and
        guardrail boundaries regardless of strategy behavior.

        Args:
            strategy: The reasoning strategy to execute.
            input: Immutable run input (task, messages, tools, budget, policy).

        Returns:
            The run's final :class:`ReasoningOutput`.
        """
        run_id = uuid.uuid4().hex
        mediator = _Mediator(
            budget=input.budget,
            policy=input.policy,
            provider=self._provider,
            tools=input.tools,
            guardrail_checks=self._guardrail_checks,
            tool_impls=self._tool_impls,
            run_id=run_id,
            tenant_id=self._tenant_id,
            strategy_id=getattr(strategy, "id", "unknown"),
            clock=self._clock,
            record_prompts=input.policy.tracing.record_prompts,
            on_event=self._on_event,
        )
        mediator._emit("reasoning.run.started", {"strategy": getattr(strategy, "id", "unknown"), "task": input.task})
        try:
            result = await self._invoke(strategy, input, mediator)
            guardrail = await mediator.verify(result.content)
            if not guardrail.passed and guardrail.action in ("block", "repair_once"):
                mediator._emit(
                    "reasoning.run.blocked",
                    {"guardrail": guardrail.guardrail_id, "action": guardrail.action},
                )
                return self._finalize(result.content, "guardrail_blocked", mediator, run_id)
            stop_reason = result.stop_reason if result.stop_reason in STOP_REASONS else "completed"
            mediator._emit("reasoning.run.completed", {"stop_reason": stop_reason})
            return self._finalize(result.content, stop_reason, mediator, run_id)
        except BudgetExceededError as exc:
            mediator._emit("reasoning.run.stopped", {"stop_reason": "budget_exhausted"})
            return ReasoningOutput(None, "budget_exhausted", exc.usage, run_id)
        except GuardrailBlockedError as exc:
            mediator._emit("reasoning.run.stopped", {"stop_reason": "guardrail_blocked"})
            return ReasoningOutput(None, "guardrail_blocked", exc.usage, run_id)
        except Exception as exc:  # noqa: BLE001 - engine boundary maps any failure to a stop_reason
            mediator._emit("reasoning.run.error", {"error": type(exc).__name__, "detail": str(exc)})
            return self._finalize(None, "error", mediator, run_id)

    async def _invoke(
        self, strategy: ReasoningStrategy, input: ReasoningInput, mediator: _Mediator
    ) -> ReasoningOutput:
        """Invoke a strategy, supporting coroutine and async-generator returns.

        Args:
            strategy: The strategy to execute.
            input: Immutable run input.
            mediator: The run mediator passed to the strategy.

        Returns:
            The :class:`ReasoningOutput` produced by the strategy.

        Raises:
            ReasoningError: If the strategy does not yield a final output.
        """
        call: Any = strategy.run(input, mediator)
        if inspect.isasyncgen(call):
            final: ReasoningOutput | None = None
            async for event in call:
                if isinstance(event, ReasoningOutput):
                    final = event
                elif isinstance(event, TraceEvent):
                    mediator.emit(event)
            if final is None:
                raise ReasoningError("streaming strategy did not yield a ReasoningOutput")
            return final
        result = await call
        if not isinstance(result, ReasoningOutput):
            raise ReasoningError("strategy.run must return a ReasoningOutput")
        return result

    def _finalize(
        self, content: Any, stop_reason: str, mediator: _Mediator, run_id: str
    ) -> ReasoningOutput:
        """Build the final output using the mediator's authoritative usage.

        Args:
            content: Final output content.
            stop_reason: Terminal stop reason (already validated).
            mediator: The run mediator holding accumulated usage.
            run_id: Identifier used as the output's ``trace_id``.

        Returns:
            The finalized :class:`ReasoningOutput`.
        """
        return ReasoningOutput(content=content, stop_reason=stop_reason, usage=mediator.usage, trace_id=run_id)


def _render_prompt(messages: Sequence[Mapping[str, Any]]) -> str:
    """Render role-tagged messages into a single prompt string.

    Args:
        messages: Ordered role/content mappings.

    Returns:
        A newline-joined ``"role: content"`` prompt; empty string if no messages.
    """
    lines = [f"{message.get('role', 'user')}: {message.get('content', '')}" for message in messages]
    return "\n".join(lines)


def _usage_payload(usage: Usage) -> dict[str, Any]:
    """Serialize a :class:`Usage` snapshot for a trace payload.

    Args:
        usage: The usage snapshot to serialize.

    Returns:
        A JSON-serializable mapping of the usage fields.
    """
    return {
        "tokens": usage.tokens,
        "cost_usd": usage.cost_usd,
        "wall_clock_ms": usage.wall_clock_ms,
        "steps": usage.steps,
    }


def budget_from_policy(policy: ReasoningPolicy) -> Budget:
    """Derive a run :class:`Budget` from a policy's declared budget.

    Args:
        policy: The reasoning policy whose budget ceiling to use.

    Returns:
        A :class:`Budget` mirroring the policy's ``budget`` section.
    """
    return Budget(
        tokens=policy.budget.tokens,
        cost_usd=policy.budget.cost_usd,
        wall_clock_ms=policy.budget.wall_clock_ms,
        max_steps=policy.budget.max_steps,
    )


__all__ = ["GuardrailCheck", "ReasoningEngine", "ToolImplementation", "budget_from_policy"]
