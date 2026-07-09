"""Mapping of E2 agent roles onto live timeline step actors (E16-S1-T3).

The redesigned UI (E17) renders a per-run "timeline" with four visible
stages — planning, analysis, patch, validation — each labeled with the
agent role that produced it (a "role badge"). This module is the single
place that maps the canonical E2 agent role identifiers, sourced from
:data:`backend.agents.contracts.AGENT_METADATA_MODELS` rather than
redefined here, onto those four timeline stages and onto the
``run.timeline.*`` event types added to the catalog by E16-S1-T2
(:mod:`backend.events.catalog`).

Only the five roles named by the E16-S1 story — Planner, Navigator,
Analyzer, Coder, Validator — are mapped. Architect, DevOps, and Responder
are legitimate E2 agent roles (see
:data:`backend.agents.contracts.AGENT_METADATA_MODELS`) but are not part of
the prototype's timeline surface and are intentionally left unmapped.
"""

from __future__ import annotations

from typing import Final

from backend.agents.contracts import AGENT_METADATA_MODELS

TIMELINE_STAGE_PLANNING: Final[str] = "planning"
"""Timeline stage for plan generation, produced by the ``planner`` role."""

TIMELINE_STAGE_ANALYSIS: Final[str] = "analysis"
"""Timeline stage for repository/context analysis, produced by the
``navigator`` and ``analyzer`` roles."""

TIMELINE_STAGE_PATCH: Final[str] = "patch"
"""Timeline stage for patch generation, produced by the ``coder`` role."""

TIMELINE_STAGE_VALIDATION: Final[str] = "validation"
"""Timeline stage for validation execution, produced by the ``validator``
role."""

_AGENT_ROLE_TO_TIMELINE_STAGE: Final[dict[str, str]] = {
    "planner": TIMELINE_STAGE_PLANNING,
    "navigator": TIMELINE_STAGE_ANALYSIS,
    "analyzer": TIMELINE_STAGE_ANALYSIS,
    "coder": TIMELINE_STAGE_PATCH,
    "validator": TIMELINE_STAGE_VALIDATION,
}

for _role in _AGENT_ROLE_TO_TIMELINE_STAGE:
    if _role not in AGENT_METADATA_MODELS:
        raise ValueError(
            f"timeline_roles: {_role!r} is not a registered E2 agent role in "
            "backend.agents.contracts.AGENT_METADATA_MODELS"
        )
del _role

TIMELINE_EVENT_TYPE_BY_STAGE: Final[dict[str, str]] = {
    TIMELINE_STAGE_PLANNING: "run.timeline.planning",
    TIMELINE_STAGE_ANALYSIS: "run.timeline.analysis",
    TIMELINE_STAGE_PATCH: "run.timeline.patch",
    TIMELINE_STAGE_VALIDATION: "run.timeline.validation",
}
"""Maps each timeline stage onto its ``run.timeline.*`` catalog event type."""


def timeline_stage_for_agent_role(agent_role: str) -> str | None:
    """Return the timeline stage an E2 agent role's output belongs to.

    Args:
        agent_role: A canonical agent role identifier (e.g. ``"coder"``),
            as used by :data:`backend.agents.contracts.AGENT_METADATA_MODELS`
            and :class:`backend.orchestrator.service.OrchestratorConfig`.

    Returns:
        One of :data:`TIMELINE_STAGE_PLANNING`, :data:`TIMELINE_STAGE_ANALYSIS`,
        :data:`TIMELINE_STAGE_PATCH`, :data:`TIMELINE_STAGE_VALIDATION`, or
        ``None`` if *agent_role* has no timeline stage (e.g. ``"architect"``,
        ``"devops"``, ``"responder"``).
    """
    return _AGENT_ROLE_TO_TIMELINE_STAGE.get(agent_role)


def timeline_event_type_for_agent_role(agent_role: str) -> str | None:
    """Return the ``run.timeline.*`` catalog event type for an agent role.

    Args:
        agent_role: A canonical agent role identifier (e.g. ``"validator"``).

    Returns:
        The event type name registered in
        :data:`backend.events.catalog.EVENT_CATALOG` (e.g.
        ``"run.timeline.validation"``), or ``None`` if *agent_role* has no
        timeline stage.
    """
    stage = timeline_stage_for_agent_role(agent_role)
    if stage is None:
        return None
    return TIMELINE_EVENT_TYPE_BY_STAGE[stage]


__all__ = [
    "TIMELINE_EVENT_TYPE_BY_STAGE",
    "TIMELINE_STAGE_ANALYSIS",
    "TIMELINE_STAGE_PATCH",
    "TIMELINE_STAGE_PLANNING",
    "TIMELINE_STAGE_VALIDATION",
    "timeline_event_type_for_agent_role",
    "timeline_stage_for_agent_role",
]
