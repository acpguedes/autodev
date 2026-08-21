"""Pure builders deriving execution tasks from plan steps and agent artifacts (E47-S5-T3).

``build_execution_tasks`` used to be one function with nine near-identical
inline loops, one per artifact section, all appending into a shared list.
Each loop is now its own small, independently readable builder; composition
is explicit list concatenation in :func:`build_execution_tasks` -- no
dispatch table, no hidden routing by artifact key.
"""

from __future__ import annotations

from typing import Any, List, Mapping

from backend.orchestrator.service.models import ExecutionTask


def _plan_step_tasks(plan_steps: List[str]) -> List[ExecutionTask]:
    """Build one task per plan step, in order."""
    return [
        ExecutionTask(
            task_id=f"plan-{index}",
            title=f"Plan step {index}",
            description=step,
            source_agent="planner",
            category="planning",
        )
        for index, step in enumerate(plan_steps, start=1)
    ]


def _analyzer_tasks(analyzer: Mapping[str, Any]) -> List[ExecutionTask]:
    """Build one task per analyzer-declared next action."""
    return [
        ExecutionTask(
            task_id=f"analysis-{index}",
            title=f"Analyze and refine scope {index}",
            description=item,
            source_agent="analyzer",
            category="analysis",
        )
        for index, item in enumerate(analyzer.get("next_actions", []), start=1)
    ]


def _architect_tasks(architect: Mapping[str, Any]) -> List[ExecutionTask]:
    """Build at most one frontend and one backend architecture-guidance task."""
    tasks: List[ExecutionTask] = []

    frontend_summary = architect.get("frontend", {}).get("summary")
    if frontend_summary:
        tasks.append(
            ExecutionTask(
                task_id="architecture-frontend",
                title="Apply frontend architecture guidance",
                description=frontend_summary,
                source_agent="architect",
                category="architecture",
            )
        )

    backend_summary = architect.get("backend", {}).get("summary")
    if backend_summary:
        tasks.append(
            ExecutionTask(
                task_id="architecture-backend",
                title="Apply backend architecture guidance",
                description=backend_summary,
                source_agent="architect",
                category="architecture",
            )
        )

    return tasks


def _coder_tasks(coder: Mapping[str, Any]) -> List[ExecutionTask]:
    """Build one task per declared coding task, plus one file-write task per declared file."""
    tasks: List[ExecutionTask] = []

    for index, item in enumerate(coder.get("coding_tasks", []), start=1):
        component = item.get("component", "component")
        task = item.get("task", "")
        tasks.append(
            ExecutionTask(
                task_id=f"coding-{index}",
                title=f"Implement {component}",
                description=task,
                source_agent="coder",
                category="implementation",
            )
        )

    for index, item in enumerate(coder.get("files", []), start=1):
        path = item.get("path", "")
        content = item.get("content", "")
        tasks.append(
            ExecutionTask(
                task_id=f"coding-file-{index}",
                title=f"Write {path}",
                description=f"Write real file content to {path}",
                source_agent="coder",
                category="implementation",
                files=[{"path": path, "content": content}],
            )
        )

    return tasks


def _devops_tasks(devops: Mapping[str, Any]) -> List[ExecutionTask]:
    """Build one task per declared deliverable, plus one per agent-declared command."""
    tasks: List[ExecutionTask] = []

    for key, value in (devops.get("deliverables", {}) or {}).items():
        tasks.append(
            ExecutionTask(
                task_id=f"devops-{key}",
                title=f"Prepare {key}",
                description=value,
                source_agent="devops",
                category="operations",
            )
        )

    for index, command in enumerate(devops.get("commands", []), start=1):
        tasks.append(
            ExecutionTask(
                task_id=f"devops-command-{index}",
                title=f"Run {command}",
                description=f"Run agent-declared command: {command}",
                source_agent="devops",
                category="operations",
                commands=[command],
            )
        )

    return tasks


def _validator_tasks(validator: Mapping[str, Any]) -> List[ExecutionTask]:
    """Build one task per declared validation step, plus one per agent-declared command."""
    tasks: List[ExecutionTask] = []

    for index, step in enumerate(validator.get("validation_steps", []), start=1):
        tasks.append(
            ExecutionTask(
                task_id=f"validation-{index}",
                title=f"Validation step {index}",
                description=step,
                source_agent="validator",
                category="validation",
            )
        )

    for index, command in enumerate(validator.get("commands", []), start=1):
        tasks.append(
            ExecutionTask(
                task_id=f"validation-command-{index}",
                title=f"Run {command}",
                description=f"Run agent-declared command: {command}",
                source_agent="validator",
                category="validation",
                commands=[command],
            )
        )

    return tasks


def build_execution_tasks(
    *, plan_steps: List[str], artifacts: Mapping[str, Any]
) -> List[ExecutionTask]:
    """Derive execution tasks from the plan steps and each agent's stored artifacts.

    Composed by chaining each artifact section's own builder, in the same
    order the single-function version emitted them, so task ids and ordering
    are unchanged.
    """
    tasks: List[ExecutionTask] = []
    tasks.extend(_plan_step_tasks(plan_steps))
    tasks.extend(_analyzer_tasks(artifacts.get("analyzer", {})))
    tasks.extend(_architect_tasks(artifacts.get("architect", {})))
    tasks.extend(_coder_tasks(artifacts.get("coder", {})))
    tasks.extend(_devops_tasks(artifacts.get("devops", {})))
    tasks.extend(_validator_tasks(artifacts.get("validator", {})))
    return tasks


__all__ = ["build_execution_tasks"]
