"""Typed contracts for machine-readable agent metadata."""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field


class PlannerOutput(BaseModel):
    """Structured planning steps shared with downstream agents."""

    steps: List[str] = Field(default_factory=list)


class NavigatorCandidateFile(BaseModel):
    """Structured repository file match emitted by the navigator."""

    path: str
    score: int
    reasons: List[str] = Field(default_factory=list)


class NavigatorOutput(BaseModel):
    """Repository context contract used for downstream routing."""

    query: str = ""
    root: str = ""
    total_files: int = 0
    top_directories: List[str] = Field(default_factory=list)
    candidate_files: List[NavigatorCandidateFile] = Field(default_factory=list)
    inventory_sample: List[str] = Field(default_factory=list)
    matched_terms: List[str] = Field(default_factory=list)


class AnalyzerOutput(BaseModel):
    """Change analysis contract used to focus implementation."""

    summary: str = ""
    impacted_areas: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)


class ArchitectSection(BaseModel):
    """Named architecture section with concise design bullets."""

    summary: str = ""
    decisions: List[str] = Field(default_factory=list)


class ArchitectOutput(BaseModel):
    """High-level architecture guidance for execution agents."""

    backend: ArchitectSection = Field(default_factory=ArchitectSection)
    frontend: ArchitectSection = Field(default_factory=ArchitectSection)
    infrastructure: ArchitectSection = Field(default_factory=ArchitectSection)


class CodingTask(BaseModel):
    """Single implementation task produced by the coder."""

    component: str
    task: str


class CoderOutput(BaseModel):
    """Code-oriented work breakdown for patch generation."""

    coding_tasks: List[CodingTask] = Field(default_factory=list)
    test_updates: List[str] = Field(default_factory=list)
    touched_components: List[str] = Field(default_factory=list)


class DevOpsOutput(BaseModel):
    """Automation and delivery tasks for the platform."""

    deliverables: Dict[str, str] = Field(default_factory=dict)
    operational_checks: List[str] = Field(default_factory=list)


class ValidatorOutput(BaseModel):
    """Executable validation guidance captured in structured form."""

    validation_steps: List[str] = Field(default_factory=list)
    success_criteria: List[str] = Field(default_factory=list)


class ResponderOutput(BaseModel):
    """Final response metadata compiled for the user-facing answer."""

    response_mode: str = "answer"
    summary: str = ""
    applies_user_request: bool = False
    source_agents: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)


AGENT_METADATA_MODELS = {
    "planner": PlannerOutput,
    "navigator": NavigatorOutput,
    "analyzer": AnalyzerOutput,
    "architect": ArchitectOutput,
    "coder": CoderOutput,
    "devops": DevOpsOutput,
    "validator": ValidatorOutput,
    "responder": ResponderOutput,
}


__all__ = [
    "AGENT_METADATA_MODELS",
    "AnalyzerOutput",
    "ArchitectOutput",
    "ArchitectSection",
    "CoderOutput",
    "CodingTask",
    "DevOpsOutput",
    "NavigatorCandidateFile",
    "NavigatorOutput",
    "PlannerOutput",
    "ResponderOutput",
    "ValidatorOutput",
]
