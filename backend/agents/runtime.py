"""v2 Agent Runtime with fail-closed budgets, guardrails, and metrics."""

from __future__ import annotations

import time
import uuid
import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from backend.agents.manifest import AgentBudgets, AgentManifest, ValidationError, validate_agent_io
from backend.agents.provider import LLMProvider, StubLLMProvider
from backend.agents.tools import AgentToolBroker
from backend.context.composer import ContextComposer
from backend.context.provider import ContextItem
from backend.observability.tracing import trace_run_step


class AgentHandler(Protocol):
    """Structural interface for callables that implement agent behavior."""

    def __call__(self, ctx: "AgentRuntimeContext") -> dict[str, Any]:
        """Execute the agent's logic for a single run.

        Args:
            ctx: Runtime context providing budget, tool, and LLM access.

        Returns:
            The agent's output payload.
        """
        ...


class BudgetExceeded(RuntimeError):
    """Raised when an agent run exceeds one of its configured budgets."""


@dataclass(frozen=True)
class AgentRuntimeStep:
    """Record of a single step taken during an agent run.

    Attributes:
        name: Step identifier.
        status: Step outcome, e.g. ``"completed"`` or ``"failed"``.
        reason: Machine-readable reason code, if the step did not simply complete.
        detail: Human-readable detail about the step outcome.
        elapsed_ms: Wall-clock duration of the step, in milliseconds.
    """

    name: str
    status: str
    reason: str = ""
    detail: str = ""
    elapsed_ms: float = 0.0


@dataclass(frozen=True)
class AgentRunResult:
    """Final outcome of a single agent run.

    Attributes:
        run_id: Identifier of the run.
        tenant_id: Identifier of the tenant the run was scoped to.
        status: Terminal run status, e.g. ``"completed"``, ``"failed"``, ``"blocked"``.
        stop_reason: Machine-readable reason the run stopped.
        flagged: Whether the run requires operator attention.
        output: The agent's output payload, if the run produced one.
        steps: Ordered steps recorded during the run.
        budgets: Budgets that were enforced during the run.
        metrics: Aggregate resource usage metrics for the run.
    """

    run_id: str
    tenant_id: str
    status: str
    stop_reason: str
    flagged: bool
    output: dict[str, Any] | None
    steps: list[AgentRuntimeStep]
    budgets: AgentBudgets
    metrics: dict[str, float | int]


@dataclass
class _BudgetLedger:
    """Tracks resource consumption against an agent's budgets during a run."""

    limits: AgentBudgets
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0
    steps: int = 0

    def consume(
        self,
        *,
        tokens_input: int = 0,
        tokens_output: int = 0,
        cost_usd: float = 0.0,
        tool_call: bool = False,
    ) -> None:
        """Record resource usage and enforce budgets.

        Args:
            tokens_input: Input tokens consumed.
            tokens_output: Output tokens consumed.
            cost_usd: Cost incurred, in US dollars.
            tool_call: Whether this consumption represents a tool/skill call.

        Raises:
            BudgetExceeded: If any budget limit is now exceeded.
        """
        self.tokens_input += tokens_input
        self.tokens_output += tokens_output
        self.cost_usd += cost_usd
        if tool_call:
            self.tool_calls += 1
        self._check()

    def record_step(self) -> None:
        """Increment the step counter and enforce the max-steps budget.

        Raises:
            BudgetExceeded: If the max-steps limit is now exceeded.
        """
        self.steps += 1
        self._check()

    def _check(self) -> None:
        """Raise if any tracked resource now exceeds its configured limit.

        Raises:
            BudgetExceeded: If any budget limit is exceeded.
        """
        if (
            self.tokens_input > self.limits.tokens_input
            or self.tokens_output > self.limits.tokens_output
            or self.cost_usd > self.limits.cost_usd
            or self.tool_calls > self.limits.max_tool_calls
            or self.steps > self.limits.max_steps
        ):
            raise BudgetExceeded("budget_exhausted")


@dataclass
class AgentRuntimeContext:
    """Per-run handle exposing budget tracking, tools, skills, and the LLM to a handler.

    Attributes:
        manifest: Manifest of the agent being run.
        input: Validated input payload for the run.
        run_id: Identifier of the run.
        tenant_id: Identifier of the tenant the run is scoped to.
        context_items: Composed, attributed context (E7-S4) injected before
            the handler runs when the runtime was built with a
            ``context_composer``; empty otherwise.
    """

    manifest: AgentManifest
    input: dict[str, Any]
    run_id: str
    tenant_id: str
    _ledger: _BudgetLedger
    _broker: AgentToolBroker
    _provider: LLMProvider
    _steps: list[AgentRuntimeStep] = field(default_factory=list)
    context_items: list[ContextItem] = field(default_factory=list)

    def consume_budget(
        self,
        *,
        tokens_input: int = 0,
        tokens_output: int = 0,
        cost_usd: float = 0.0,
        tool_call: bool = False,
    ) -> None:
        """Record manual resource consumption against the run's budgets.

        Args:
            tokens_input: Input tokens consumed.
            tokens_output: Output tokens consumed.
            cost_usd: Cost incurred, in US dollars.
            tool_call: Whether this consumption represents a tool/skill call.

        Raises:
            BudgetExceeded: If any budget limit is now exceeded.
        """
        self._ledger.consume(
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=cost_usd,
            tool_call=tool_call,
        )

    def record_step(self, name: str, *, status: str = "completed", reason: str = "", detail: str = "") -> None:
        """Record a traced step in the run's execution timeline.

        Args:
            name: Step identifier.
            status: Step outcome, e.g. ``"completed"``, ``"running"``, ``"failed"``.
            reason: Machine-readable reason code, if applicable.
            detail: Human-readable detail about the step outcome.

        Raises:
            BudgetExceeded: If the max-steps limit is now exceeded.
        """
        started = time.perf_counter()
        self._ledger.record_step()
        with trace_run_step(run_id=self.run_id, step_id=name, agent=self.manifest.id, status=status):
            pass
        elapsed_ms = (time.perf_counter() - started) * 1000
        self._steps.append(AgentRuntimeStep(name, status, reason, detail, elapsed_ms))

    def call_tool(self, tool_id: str, **kwargs: Any) -> Any:
        """Invoke a granted tool, counting it against the tool-call budget.

        Args:
            tool_id: Identifier of the tool to call.
            **kwargs: Keyword arguments forwarded to the tool.

        Returns:
            The tool's return value.

        Raises:
            BudgetExceeded: If the tool-call budget is now exceeded.
            ToolAccessDenied: If the tool is not granted or not registered.
        """
        self._ledger.consume(tool_call=True)
        return self._broker.call_tool(tool_id, **kwargs)

    def call_skill(self, skill_id: str, **kwargs: Any) -> Any:
        """Invoke a granted skill, counting it against the tool-call budget.

        Args:
            skill_id: Identifier of the skill to call.
            **kwargs: Keyword arguments forwarded to the skill.

        Returns:
            The skill's return value.

        Raises:
            BudgetExceeded: If the tool-call budget is now exceeded.
            ToolAccessDenied: If the skill is not granted or not registered.
        """
        self._ledger.consume(tool_call=True)
        return self._broker.call_skill(skill_id, **kwargs)

    def call_llm(self, prompt: str) -> str:
        """Complete a prompt via the configured LLM provider and track usage.

        Args:
            prompt: Fully rendered prompt text.

        Returns:
            The completion text.

        Raises:
            BudgetExceeded: If a token or cost budget is now exceeded.
        """
        response = self._provider.complete(
            prompt,
            agent_id=self.manifest.id,
            run_id=self.run_id,
            tenant_id=self.tenant_id,
        )
        self.consume_budget(
            tokens_input=response.tokens_input,
            tokens_output=response.tokens_output,
            cost_usd=response.cost_usd,
        )
        return response.text


class AgentRuntime:
    """Executes agent handlers under fail-closed budgets and guardrails."""

    def __init__(
        self,
        *,
        tools: dict[str, Any] | None = None,
        skills: dict[str, Any] | None = None,
        provider: LLMProvider | None = None,
        context_composer: ContextComposer | None = None,
    ) -> None:
        """Initialize the runtime with shared tools, skills, LLM provider, and context policy.

        Args:
            tools: Mapping of tool id to callable implementation, if any.
            skills: Mapping of skill id to callable implementation, if any.
            provider: LLM provider to use; defaults to :class:`StubLLMProvider`.
            context_composer: Composer (E7-S4) whose output is attached to
                every run's :attr:`AgentRuntimeContext.context_items`; the
                composer's provider list/weights/timeouts are the
                policy-driven part — the runtime itself just injects
                whatever it produces. ``None`` (default) means no context
                injection.
        """
        self._tools = tools or {}
        self._skills = skills or {}
        self._provider = provider or StubLLMProvider()
        self._context_composer = context_composer

    def run(
        self,
        manifest: AgentManifest,
        payload: dict[str, Any],
        handler: AgentHandler | Any,
        *,
        run_id: str | None = None,
        tenant_id: str = "default",
        budgets: AgentBudgets | None = None,
        context_query: str = "",
    ) -> AgentRunResult:
        """Run an agent handler end-to-end with validation and guardrails.

        Args:
            manifest: Manifest of the agent to run.
            payload: Input payload to validate and pass to the handler.
            handler: Callable or object exposing ``run(ctx)`` implementing the agent.
            run_id: Identifier to use for this run; generated if omitted.
            tenant_id: Identifier of the tenant the run is scoped to.
            budgets: Budgets to enforce; defaults to the manifest's declared budgets.
            context_query: Query forwarded to the runtime's ``context_composer``
                (if any) to focus what context is composed for this run;
                ignored when no composer is configured.

        Returns:
            The final :class:`AgentRunResult`, whatever the outcome.
        """
        active_run_id = run_id or str(uuid.uuid4())
        active_budgets = budgets or manifest.budgets
        ledger = _BudgetLedger(active_budgets)
        broker = AgentToolBroker(manifest, tools=self._tools, skills=self._skills)
        ctx = AgentRuntimeContext(manifest, payload, active_run_id, tenant_id, ledger, broker, self._provider)
        if self._context_composer is not None:
            ctx.context_items = self._context_composer.compose(context_query, tenant_id=tenant_id).items

        try:
            validate_agent_io(manifest, payload, "input")
            ctx.record_step("validate-input", status="completed")
            ctx.record_step("run-handler", status="running")
            output = self._invoke_handler(handler, ctx)
            ctx.record_step("handler-completed", status="completed")
            validate_agent_io(manifest, output, "output")
            ctx.record_step("validate-output", status="completed")
            violation = self._guardrail_violation(manifest, output)
            if violation:
                ctx.record_step("guardrail-output", status="failed", reason="guardrail_blocked", detail=violation)
                return self._result(ctx, "blocked", "guardrail_blocked", True, None, active_budgets)
            return self._result(ctx, "completed", "completed", False, output, active_budgets)
        except BudgetExceeded as exc:
            self._append_failed_step(ctx, "budget", "budget_exhausted", str(exc))
            return self._result(ctx, "interrupted", "budget_exhausted", True, None, active_budgets)
        except ValidationError as exc:
            self._append_failed_step(ctx, "validate-output", "invalid_output", str(exc))
            return self._result(ctx, "failed", "invalid_output", True, None, active_budgets)
        except Exception as exc:  # noqa: BLE001 - runtime isolates agent failures
            self._append_failed_step(ctx, "handler-error", "handler_failed", str(exc))
            return self._result(ctx, "failed", "handler_failed", True, None, active_budgets)

    def _invoke_handler(self, handler: AgentHandler | Any, ctx: AgentRuntimeContext) -> dict[str, Any]:
        """Invoke a handler, accepting either a callable or a ``run(ctx)``-style object.

        Args:
            handler: Callable or object exposing ``run(ctx)``.
            ctx: Runtime context to pass to the handler.

        Returns:
            The handler's output payload.

        Raises:
            TypeError: If ``handler`` is neither callable nor exposes ``run``.
            ValidationError: If the handler's output is not an object.
        """
        if callable(handler):
            output = handler(ctx)
        elif hasattr(handler, "run"):
            output = handler.run(ctx)
        else:
            raise TypeError("agent handler must be callable or expose run(ctx)")
        if not isinstance(output, dict):
            raise ValidationError("agent output must be an object")
        return output

    def _guardrail_violation(self, manifest: AgentManifest, output: dict[str, Any]) -> str:
        """Check agent output against denylist guardrails declared in its policy.

        Args:
            manifest: Manifest whose policy declares the guardrails to check.
            output: Agent output to check.

        Returns:
            A human-readable violation description, or an empty string if none matched.
        """
        guardrails = manifest.policy.get("guardrails", [])
        if not isinstance(guardrails, list):
            return ""
        rendered = str(output)
        for guardrail in guardrails:
            if not isinstance(guardrail, dict) or guardrail.get("type") != "denylist":
                continue
            action = guardrail.get("onViolation", "block")
            for term in guardrail.get("terms", []):
                if isinstance(term, str) and term and term in rendered and action == "block":
                    return f"denylist term {term!r} matched output"
        return ""

    def _append_failed_step(self, ctx: AgentRuntimeContext, name: str, reason: str, detail: str) -> None:
        """Append a failed step to the run's timeline and emit a trace event.

        Args:
            ctx: Runtime context whose step list is being appended to.
            name: Step identifier.
            reason: Machine-readable failure reason code.
            detail: Human-readable failure detail.
        """
        with trace_run_step(run_id=ctx.run_id, step_id=name, agent=ctx.manifest.id, status="failed"):
            pass
        ctx._steps.append(AgentRuntimeStep(name=name, status="failed", reason=reason, detail=detail))

    def _result(
        self,
        ctx: AgentRuntimeContext,
        status: str,
        stop_reason: str,
        flagged: bool,
        output: dict[str, Any] | None,
        budgets: AgentBudgets,
    ) -> AgentRunResult:
        """Assemble the final :class:`AgentRunResult` from a run's context.

        Args:
            ctx: Runtime context accumulated during the run.
            status: Terminal run status.
            stop_reason: Machine-readable reason the run stopped.
            flagged: Whether the run requires operator attention.
            output: The agent's output payload, if any.
            budgets: Budgets that were enforced during the run.

        Returns:
            The assembled run result.
        """
        return AgentRunResult(
            run_id=ctx.run_id,
            tenant_id=ctx.tenant_id,
            status=status,
            stop_reason=stop_reason,
            flagged=flagged,
            output=output,
            steps=list(ctx._steps),
            budgets=budgets,
            metrics={
                "tokens.input": ctx._ledger.tokens_input,
                "tokens.output": ctx._ledger.tokens_output,
                "cost.usd": ctx._ledger.cost_usd,
                "tool.calls": ctx._ledger.tool_calls,
                "steps": len(ctx._steps),
            },
        )

    def load_handler(self, manifest: AgentManifest, base_dir: Path | str) -> Any:
        """Load and instantiate the handler referenced by an agent's entrypoint.

        Args:
            manifest: Manifest whose entrypoint references the handler.
            base_dir: Directory to resolve the entrypoint's module from.

        Returns:
            A handler instance ready to be passed to :meth:`run`.
        """
        module_name, object_name = manifest.entrypoint.ref.split(":", 1)
        module = self._load_module(module_name, Path(base_dir))
        handler = getattr(module, object_name)
        if isinstance(handler, type):
            return handler()
        return handler

    def _load_module(self, module_name: str, base_dir: Path) -> Any:
        """Import a handler's module from a local file or the Python path.

        Args:
            module_name: Dotted module name from the entrypoint reference.
            base_dir: Directory to look for a matching local ``.py`` file in.

        Returns:
            The imported module.

        Raises:
            ImportError: If a local module file exists but cannot be loaded.
        """
        module_file = base_dir / f"{module_name.rsplit('.', 1)[-1]}.py"
        if module_file.exists():
            spec = importlib.util.spec_from_file_location(f"_autodev_agent_{module_name}", module_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot import {module_name} from {module_file}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
        sys.path.insert(0, str(base_dir))
        try:
            return importlib.import_module(module_name)
        finally:
            if sys.path and sys.path[0] == str(base_dir):
                sys.path.pop(0)


__all__ = [
    "AgentRunResult",
    "AgentRuntime",
    "AgentRuntimeContext",
    "AgentRuntimeStep",
    "BudgetExceeded",
]
