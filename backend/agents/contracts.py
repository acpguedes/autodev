"""Typed contracts for machine-readable agent metadata."""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field, field_validator

#: Maximum number of files a single Coder agent call may propose (E41-S2-T3):
#: bounds generation scope so one call can't attempt an unbounded rewrite.
CODER_MAX_FILES = 20

#: Maximum content size (bytes, UTF-8) per proposed file (E41-S2-T3).
CODER_MAX_FILE_BYTES = 64_000


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


class CoderFile(BaseModel):
    """One real, runnable file proposed by the coder for patch application."""

    path: str
    content: str


class CoderOutput(BaseModel):
    """Code-oriented work breakdown for patch generation."""

    coding_tasks: List[CodingTask] = Field(default_factory=list)
    files: List[CoderFile] = Field(default_factory=list)
    test_updates: List[str] = Field(default_factory=list)
    touched_components: List[str] = Field(default_factory=list)

    @field_validator("files")
    @classmethod
    def _bound_generation_scope(cls, value: List[CoderFile]) -> List[CoderFile]:
        """Cap file count/size so a single coder call can't attempt an unbounded rewrite."""

        if len(value) > CODER_MAX_FILES:
            raise ValueError(
                f"coder proposed {len(value)} files, exceeding the Beta cap of {CODER_MAX_FILES}"
            )
        for item in value:
            size = len(item.content.encode("utf-8"))
            if size > CODER_MAX_FILE_BYTES:
                raise ValueError(
                    f"file {item.path!r} is {size} bytes, exceeding the Beta cap of "
                    f"{CODER_MAX_FILE_BYTES} bytes"
                )
        return value


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
    "CoderFile",
    "CoderOutput",
    "CodingTask",
    "DevOpsOutput",
    "NavigatorCandidateFile",
    "NavigatorOutput",
    "PlannerOutput",
    "ResponderOutput",
    "ValidatorOutput",
]
