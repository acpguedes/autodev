"""Skill-to-skill composition into sequential pipelines (E6-S4).

Deliberately does not reuse the Flow Engine (`backend/flows/engine.py`):
composition here stays skill-to-skill, resolved and budgeted purely through
the Skill Registry/Invocation Broker; flow-node wiring is a separate, later
integration (E6 only enables it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.skills.invoker import SkillBudgetExceeded, SkillInvocationBroker, SkillInvocationDenied
from backend.skills.manifest import SkillManifest
from backend.skills.registry_v2 import SkillRegistry


class SkillCompositionError(RuntimeError):
    """Raised when a skill pipeline cannot be resolved or a step fails.

    Attributes:
        step_index: Index of the pipeline step that failed.
        skill_id: Id of the skill at that step.
        reason: Machine-readable failure reason.
    """

    def __init__(self, step_index: int, skill_id: str, reason: str) -> None:
        """Initialize the error with the failing step's position and reason."""
        self.step_index = step_index
        self.skill_id = skill_id
        self.reason = reason
        super().__init__(f"pipeline step {step_index} ({skill_id}) failed: {reason}")


@dataclass(frozen=True)
class PipelineStep:
    """A single step in a skill composition pipeline.

    Attributes:
        skill_id: Fully qualified skill id to invoke at this step.
        version_range: SemVer range expression selecting the version.
    """

    skill_id: str
    version_range: str = "*"


def _resolve_all(steps: tuple[PipelineStep, ...], registry: SkillRegistry) -> list[SkillManifest]:
    """Resolve every step's manifest and its declared dependencies upfront.

    Args:
        steps: Ordered pipeline steps to resolve.
        registry: Skill Registry used for resolution.

    Returns:
        The resolved manifest for each step, in order.

    Raises:
        SkillCompositionError: If any step or its declared dependency is missing,
            before any step has executed.
    """
    manifests: list[SkillManifest] = []
    for index, step in enumerate(steps):
        try:
            ref = registry.resolve(step.skill_id, step.version_range)
        except KeyError:
            raise SkillCompositionError(index, step.skill_id, "missing-dependency") from None
        for dependency in ref.manifest.dependencies:
            try:
                registry.resolve(dependency.id, dependency.version)
            except KeyError:
                raise SkillCompositionError(index, dependency.id, "missing-dependency") from None
        manifests.append(ref.manifest)
    return manifests


def run_pipeline(
    steps: list[PipelineStep],
    initial_input: dict[str, Any],
    *,
    registry: SkillRegistry,
    invoker: SkillInvocationBroker,
    max_total_timeout_sec: float | None = None,
) -> dict[str, Any]:
    """Run an ordered chain of skills, feeding each step's output to the next.

    All steps and their declared dependencies are resolved before any step
    executes, so a missing dependency is reported with no side effects. On a
    mid-pipeline failure, execution stops immediately at that step; steps
    before it have already run (as any sequential process does), but no
    further steps run and the failure is reported precisely.

    Args:
        steps: Ordered pipeline steps to execute.
        initial_input: Input payload for the first step.
        registry: Skill Registry used to resolve steps and their dependencies.
        invoker: Broker used to actually invoke each resolved skill.
        max_total_timeout_sec: If given, the sum of every step's declared
            timeout budget must not exceed this, checked before execution.

    Returns:
        The final step's output payload.

    Raises:
        SkillCompositionError: If resolution fails, the aggregated budget is
            exceeded, or a step raises during execution.
    """
    manifests = _resolve_all(tuple(steps), registry)

    if max_total_timeout_sec is not None:
        total_timeout = sum(manifest.budgets.timeout_sec for manifest in manifests)
        if total_timeout > max_total_timeout_sec:
            raise SkillCompositionError(
                0, steps[0].skill_id if steps else "", "aggregated-budget-exceeded"
            )

    current: dict[str, Any] = initial_input
    for index, step in enumerate(steps):
        try:
            current = invoker.invoke(step.skill_id, step.version_range, **current)
        except SkillInvocationDenied as exc:
            raise SkillCompositionError(index, step.skill_id, "denied") from exc
        except SkillBudgetExceeded as exc:
            raise SkillCompositionError(index, step.skill_id, "budget-exceeded") from exc
    return current


__all__ = ["PipelineStep", "SkillCompositionError", "run_pipeline"]
