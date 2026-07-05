from __future__ import annotations

from typing import Any

from backend.agents.base import AgentContext
from backend.agents.coder.agent import CoderAgent
from backend.agents.runtime import AgentRuntimeContext
from backend.sdk.contracts import HostApi


def register(host: HostApi) -> None:
    host.register_extension("agent", "autodev/agent-coder.agent", {"manifest": "agent.yaml"})


class AgentCoder:
    def __call__(self, ctx: AgentRuntimeContext) -> dict[str, Any]:
        task = ctx.input.get("task", {})
        plan = task.get("plan", []) if isinstance(task, dict) else []
        goal = task.get("goal", "") if isinstance(task, dict) else ""
        user_request = task.get("userRequest", goal) if isinstance(task, dict) else goal
        context = AgentContext(
            session_id=ctx.run_id,
            goal=goal,
            user_request=user_request,
            artifacts={"planner": {"steps": list(plan)}},
        )
        fallback = CoderAgent().fallback_result(context)
        metadata = dict(fallback.metadata)
        return {
            "schemaVersion": "1.0.0",
            "status": "ok",
            "codingTasks": metadata.get("coding_tasks", []),
            "testUpdates": metadata.get("test_updates", []),
            "touchedComponents": metadata.get("touched_components", []),
        }
