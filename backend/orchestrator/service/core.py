"""``OrchestratorService``: composes every mixin into one coordinating class (E47-S5)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping

from backend.agents import Agent, AgentResult
from backend.environments.manager import EnvironmentManager
from backend.execution.decisions import DecisionService
from backend.execution.executor import TaskExecutor
from backend.execution.policy import PolicyService
from backend.execution.runner import InProcessActionRunner
from backend.orchestrator.service.chat import ChatMixin
from backend.orchestrator.service.graph import GraphMixin
from backend.orchestrator.service.models import HistoryItem, OrchestratorConfig, RunType
from backend.orchestrator.service.plan_lifecycle import PlanLifecycleMixin
from backend.orchestrator.service.queries import QueryMixin
from backend.orchestrator.service.self_repair import SelfRepairMixin
from backend.orchestrator.service.task_dispatch import TaskDispatchMixin
from backend.persistence import DurableStore, get_store
from backend.quotas.contracts import QuotaDenialReason, QuotaExceededError, QuotaResource
from backend.quotas.service import QuotaService


class OrchestratorService(
    ChatMixin,
    QueryMixin,
    PlanLifecycleMixin,
    TaskDispatchMixin,
    SelfRepairMixin,
    GraphMixin,
):
    """Coordinate agent execution for a durable session.

    Split by concern across this package's modules (E47-S5):
    :mod:`chat` (plan-session creation and the message-driven graph run),
    :mod:`queries` (session/run listings), :mod:`plan_lifecycle` (derive/
    execute/resume/finalize the task-execution plan), :mod:`task_dispatch`
    (per-batch environment lifecycle and action resolution), :mod:`self_repair`
    (batched Coder repair), and :mod:`graph` (agent registry and the
    per-message LangGraph workflow). This class itself only owns
    construction and the handful of small, generic utilities every mixin
    shares.
    """

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        agents: Mapping[str, Agent] | None = None,
        store: DurableStore | None = None,
        project_root: Path | None = None,
        quota_service: QuotaService | None = None,
        policy_service: PolicyService | None = None,
        decision_service: DecisionService | None = None,
        environment_manager: EnvironmentManager | None = None,
    ) -> None:
        """Initialize the service, wiring default agents and the durable store.

        Args:
            config: Orchestrator configuration; defaults to :class:`OrchestratorConfig`.
            agents: Additional or overriding agents, merged over the defaults.
            store: Durable store to use; defaults to :func:`backend.persistence.get_store`.
            project_root: Repository root passed to agents that need filesystem access.
            quota_service: Tenant quota/budget service (E11-S3, ADR-019); defaults
                to a fresh :class:`~backend.quotas.service.QuotaService`. Governs
                the per-tenant concurrent-run admission control in
                :meth:`~backend.orchestrator.service.chat.ChatMixin.handle_message`/
                :meth:`~backend.orchestrator.service.plan_lifecycle.PlanLifecycleMixin.execute_plan`.
            policy_service: Execution policy engine (E14-S2, ADR-022); defaults
                to a fresh :class:`~backend.execution.policy.PolicyService`.
                Gates every action
                :meth:`~backend.orchestrator.service.plan_lifecycle.PlanLifecycleMixin.execute_plan`
                dispatches.
            decision_service: Human-decision service (E14-S3); defaults to a
                fresh :class:`~backend.execution.decisions.DecisionService`.
                Backs approval/hybrid-mode pauses in
                :meth:`~backend.orchestrator.service.plan_lifecycle.PlanLifecycleMixin.execute_plan`/
                :meth:`~backend.orchestrator.service.plan_lifecycle.PlanLifecycleMixin.resume_plan_execution`.
            environment_manager: Isolated execution-environment lifecycle
                manager (E32); defaults to a fresh
                :class:`~backend.environments.manager.EnvironmentManager`.
                :meth:`~backend.orchestrator.service.task_dispatch.TaskDispatchMixin._process_tasks`
                provisions one environment per dispatch batch, scopes every
                derived action's runner to it, and tears it down (collecting
                artifacts) once the batch finishes or pauses.
        """
        self._config = config or OrchestratorConfig()
        self._project_root = project_root
        self._agents = self._build_default_agents()
        if agents:
            self._agents.update(agents)
        self._store = store or get_store()
        self._quota_service = quota_service or QuotaService()
        self._policy_service = policy_service or PolicyService()
        self._decision_service = decision_service or DecisionService()
        self._environment_manager = environment_manager or EnvironmentManager()
        self._graph = self._compile_graph()
        self._composite_runner = InProcessActionRunner(
            project_root=(self._project_root or Path(".")).resolve(),
            environment_manager=self._environment_manager,
        )
        self._task_executor = TaskExecutor(self._composite_runner, policy=self._policy_service)

    def _acquire_run_lease(self, *, tenant_id: str, run_id: str) -> None:
        """Admit a new run against the tenant's concurrent-run ceiling, or fail closed.

        Args:
            tenant_id: Tenant the run belongs to.
            run_id: Identifier already generated for the run about to start.

        Raises:
            QuotaExceededError: If the tenant is already at its concurrent-run
                limit. No run record is created and no lease is held.
        """
        lease = self._quota_service.acquire_run_lease(tenant_id=tenant_id, run_id=run_id)
        if not lease.granted:
            policy = self._quota_service.resolve_policy(tenant_id)
            raise QuotaExceededError(
                resource=QuotaResource.CONCURRENT_RUNS,
                reason=QuotaDenialReason.LEASE_UNAVAILABLE,
                used=policy.max_concurrent_runs,
                limit=policy.max_concurrent_runs,
            )

    def _extract_plan_steps(self, plan_result: AgentResult) -> List[str]:
        """Extract plan steps from planner metadata, falling back to parsing bullet lines."""
        plan_steps = list(plan_result.metadata.get("steps", []))
        if plan_steps:
            return plan_steps

        extracted_steps: List[str] = []
        for line in plan_result.content.splitlines():
            stripped_line = line.strip()
            if not stripped_line or not stripped_line.startswith("-"):
                continue
            cleaned_step = stripped_line.lstrip("- ").strip()
            if cleaned_step:
                extracted_steps.append(cleaned_step)
        return extracted_steps

    def _clone_artifacts(
        self, artifacts: Mapping[str, Mapping[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Deep-copy one level of an artifacts mapping so callers can mutate it safely."""
        return {name: dict(meta) for name, meta in artifacts.items()}

    def _infer_run_type(self, *, goal: str, message: str) -> RunType:
        """Infer the run type from keyword heuristics over the goal and message."""
        combined = f"{goal} {message}".lower()
        if any(keyword in combined for keyword in ("doc", "readme", "documentation")):
            return RunType.DOCUMENTATION_UPDATE
        if any(
            keyword in combined
            for keyword in ("infra", "deploy", "docker", "kubernetes", "terraform")
        ):
            return RunType.DEVOPS_CHANGE
        if any(
            keyword in combined
            for keyword in ("validate", "validation", "test", "lint", "typecheck")
        ):
            return RunType.VALIDATION_ONLY
        if any(
            keyword in combined
            for keyword in ("bootstrap", "greenfield", "new project", "from scratch")
        ):
            return RunType.GREENFIELD_BOOTSTRAP
        return RunType.EXISTING_REPO_CHANGE

    def _normalize_execution_history(
        self, history: List[HistoryItem]
    ) -> List[HistoryItem]:
        """Reorder history so non-executor entries precede executor progress entries."""
        if not history:
            return []

        ordered = [item for item in history if item.role != "executor"]
        ordered.extend(item for item in history if item.role == "executor")
        return ordered

    def _timestamp(self) -> str:
        """Return the current UTC timestamp, second precision, in ``Z``-suffixed ISO 8601."""
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )


__all__ = ["OrchestratorConfig", "OrchestratorService"]
