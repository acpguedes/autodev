"""Request/response schemas for the ``/v2/plans`` router (E16-S2 / E17-S2).

Split out of ``plan_approval_v2.py`` to keep that module under the
repository's 500-line-per-file limit. Pure data models — no request
handling logic lives here.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from backend.api.v2_common import SCHEMA_VERSION_V2


class PlanStepV2(BaseModel):
    """A single plan step and its current approval state."""

    schemaVersion: str = SCHEMA_VERSION_V2
    session_id: str
    step_index: int
    content: str
    state: str
    updated_at: str


class PlanV2(BaseModel):
    """A session's plan, rolled up from its steps' individual states."""

    schemaVersion: str = SCHEMA_VERSION_V2
    session_id: str
    status: str
    steps: list[PlanStepV2]


class StepContentUpdateRequestV2(BaseModel):
    """Request body for ``PUT /v2/plans/{session_id}/steps/{step_index}``."""

    content: str = Field(..., min_length=1, description="New content for the step.")


class StepCreateRequestV2(BaseModel):
    """Request body for ``POST /v2/plans/{session_id}/steps``."""

    content: str = Field(..., min_length=1, description="Content for the new step.")
    actor: str = "anonymous"


class StepDecisionRequestV2(BaseModel):
    """Request body for the ``approve``/``reject`` step actions."""

    actor: str = "anonymous"
    note: str = ""


class ExecuteApprovedRequestV2(BaseModel):
    """Request body for ``POST /v2/plans/{session_id}/execute-approved``.

    When ``step_indices`` is omitted, every currently-``approved`` step is
    executed. When given explicitly, every listed index must already be
    ``approved`` — attempting to execute a ``rejected`` or still-pending
    step is denied as an illegal transition (E16-S2-T2).
    """

    step_indices: Optional[list[int]] = None
    actor: str = "anonymous"


__all__ = [
    "ExecuteApprovedRequestV2",
    "PlanStepV2",
    "PlanV2",
    "StepContentUpdateRequestV2",
    "StepCreateRequestV2",
    "StepDecisionRequestV2",
]
