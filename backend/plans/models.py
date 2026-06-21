"""Data models for the plan store."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PlanStatus(StrEnum):
    """Lifecycle states for a plan document."""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class PlanDocument:
    """A persisted plan associated with a session."""

    session_id: str
    steps: list[str]
    status: str
    updated_at: str


@dataclass
class ApprovalRecord:
    """A single approval or rejection decision for a plan."""

    session_id: str
    decision: str
    actor: str
    note: str
    created_at: str


__all__ = [
    "PlanStatus",
    "PlanDocument",
    "ApprovalRecord",
]
