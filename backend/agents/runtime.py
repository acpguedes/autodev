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
from backend.observability.tracing import trace_run_step


class AgentHandler(Protocol):
    def __call__(self, ctx: "AgentRuntimeContext") -> dict[str, Any]: ...


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentRuntimeStep:
    name: str
    status: str
    reason: str = ""
    detail: str = ""
    elapsed_ms: float = 0.0


@dataclass(frozen=True)
class AgentRunResult:
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
        self.tokens_input += tokens_input
        self.tokens_output += tokens_output
        self.cost_usd += cost_usd
        if tool_call:
            self.tool_calls += 1
        self._check()

    def record_step(self) -> None:
        self.steps += 1
        self._check()

    def _check(self) -> None:
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
    manifest: AgentManifest
    input: dict[str, Any]
    run_id: str
    tenant_id: str
    _ledger: _BudgetLedger
    _broker: AgentToolBroker
    _provider: LLMProvider
    _steps: list[AgentRuntimeStep] = field(default_factory=list)

    def consume_budget(
        self,
        *,
        tokens_input: int = 0,
        tokens_output: int = 0,
        cost_usd: float = 0.0,
        tool_call: bool = False,
    ) -> None:
        self._ledger.consume(
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=cost_usd,
            tool_call=tool_call,
        )

    def record_step(self, name: str, *, status: str = "completed", reason: str = "", detail: str = "") -> None:
        started = time.perf_counter()
        self._ledger.record_step()
        with trace_run_step(run_id=self.run_id, step_id=name, agent=self.manifest.id, status=status):
            pass
        elapsed_ms = (time.perf_counter() - started) * 1000
        self._steps.append(AgentRuntimeStep(name, status, reason, detail, elapsed_ms))

    def call_tool(self, tool_id: str, **kwargs: Any) -> Any:
        self._ledger.consume(tool_call=True)
        return self._broker.call_tool(tool_id, **kwargs)

    def call_skill(self, skill_id: str, **kwargs: Any) -> Any:
        self._ledger.consume(tool_call=True)
        return self._broker.call_skill(skill_id, **kwargs)

    def call_llm(self, prompt: str) -> str:
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
    def __init__(
        self,
        *,
        tools: dict[str, Any] | None = None,
        skills: dict[str, Any] | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self._tools = tools or {}
        self._skills = skills or {}
        self._provider = provider or StubLLMProvider()

    def run(
        self,
        manifest: AgentManifest,
        payload: dict[str, Any],
        handler: AgentHandler | Any,
        *,
        run_id: str | None = None,
        tenant_id: str = "default",
        budgets: AgentBudgets | None = None,
    ) -> AgentRunResult:
        active_run_id = run_id or str(uuid.uuid4())
        active_budgets = budgets or manifest.budgets
        ledger = _BudgetLedger(active_budgets)
        broker = AgentToolBroker(manifest, tools=self._tools, skills=self._skills)
        ctx = AgentRuntimeContext(manifest, payload, active_run_id, tenant_id, ledger, broker, self._provider)

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
        module_name, object_name = manifest.entrypoint.ref.split(":", 1)
        module = self._load_module(module_name, Path(base_dir))
        handler = getattr(module, object_name)
        if isinstance(handler, type):
            return handler()
        return handler

    def _load_module(self, module_name: str, base_dir: Path) -> Any:
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
