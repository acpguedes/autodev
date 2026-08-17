"""v2 Control Plane API — pending execution-action decisions (E14-S3).

Approval/hybrid execution modes pause a plan-execution run on a
:class:`~backend.execution.policy.PendingDecision`. This router lets an
operator list and resolve them; resuming the paused run itself is
``POST /v2/sessions/{id}/execution-plan/resume`` (``sessions_v2.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.api.authorization import requires_scope
from backend.api.rbac_v2 import PrincipalV2, require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2, v2_error
from backend.execution.decisions import DecisionAlreadyResolvedError, DecisionNotFoundError
from backend.execution.policy import PendingDecision
from backend.orchestrator.service import OrchestratorConfig, OrchestratorService

router = APIRouter(
    prefix="/v2/execution/decisions", tags=["execution-decisions"], dependencies=[Depends(require_v2_principal)]
)


def get_orchestrator_v2() -> OrchestratorService:
    """Build an :class:`OrchestratorService`, matching every other ``/v2`` router.

    Resolving/listing decisions is routed through the orchestrator (rather
    than :class:`~backend.execution.decisions.DecisionService` directly) so
    a hybrid "always" resolution can also grant the dynamic permission via
    the same policy service the orchestrator's runs are gated by.

    Returns:
        A new :class:`OrchestratorService`.
    """
    return OrchestratorService(config=OrchestratorConfig())


class PendingDecisionV2(BaseModel):
    """One pending execution-action decision, as exposed over the API."""

    model_config = ConfigDict(populate_by_name=True)

    decision_id: str = Field(alias="decisionId")
    run_id: str = Field(alias="runId")
    task_id: str = Field(alias="taskId")
    category: str
    prompt: str
    status: str
    created_at: str = Field(alias="createdAt")
    expires_at: str = Field(alias="expiresAt")

    @classmethod
    def from_decision(cls, decision: PendingDecision) -> "PendingDecisionV2":
        """Build the API model from a domain :class:`PendingDecision`."""
        return cls(
            decisionId=decision.decision_id,
            runId=decision.run_id,
            taskId=decision.task_id,
            category=decision.category.value,
            prompt=decision.prompt,
            status=decision.status.value,
            createdAt=decision.created_at,
            expiresAt=decision.expires_at,
        )


class PendingDecisionListV2(BaseModel):
    """The caller's tenant's still-pending execution-action decisions."""

    schemaVersion: str = SCHEMA_VERSION_V2
    decisions: list[PendingDecisionV2]


class ResolveDecisionRequestV2(BaseModel):
    """Request body for ``POST /v2/execution/decisions/{id}/resolve``."""

    model_config = ConfigDict(populate_by_name=True)

    decision: str = Field(description="'approve' or 'deny'.")
    persist_as_rule: bool = Field(
        default=False,
        alias="persistAsRule",
        description="Hybrid mode's \"always\" option: also grant a durable dynamic permission.",
    )


@requires_scope("run:read")
@router.get("", response_model=PendingDecisionListV2)
def list_pending_decisions_v2(
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> PendingDecisionListV2:
    """List the caller's own tenant's still-pending execution-action decisions.

    Args:
        orchestrator: Orchestrator service dependency.
        principal: Authenticated caller; its tenant is the only tenant this
            endpoint can ever query.

    Returns:
        Every decision still :attr:`~backend.execution.policy.DecisionStatus.PENDING`
        for the caller's tenant (self-expiring any that are past due).
    """
    decisions = orchestrator.list_pending_execution_decisions(tenant_id=principal.tenant_id)
    return PendingDecisionListV2(decisions=[PendingDecisionV2.from_decision(d) for d in decisions])


@requires_scope("run:write")
@router.post("/{decision_id}/resolve", response_model=PendingDecisionV2)
def resolve_decision_v2(
    decision_id: str,
    request: ResolveDecisionRequestV2,
    orchestrator: OrchestratorService = Depends(get_orchestrator_v2),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> PendingDecisionV2:
    """Approve or deny a pending execution-action decision.

    Args:
        decision_id: The decision to resolve.
        request: The resolution (approve/deny, optional "always" persist).
        orchestrator: Orchestrator service dependency.
        principal: Authenticated caller (must hold ``run:write``); its
            tenant is the only tenant this endpoint can ever resolve for.

    Returns:
        The resolved decision.

    Raises:
        HTTPException: 400 if ``decision`` is neither "approve" nor "deny";
            404 if no such decision exists for the caller's tenant; 409 if
            it was already resolved (including a concurrent timeout).
    """
    try:
        resolved = orchestrator.resolve_execution_decision(
            decision_id,
            tenant_id=principal.tenant_id,
            decision=request.decision,
            actor=principal.subject,
            persist_as_rule=request.persist_as_rule,
        )
    except ValueError as exc:
        v2_error(400, str(exc))
    except DecisionNotFoundError as exc:
        v2_error(404, str(exc))
    except DecisionAlreadyResolvedError as exc:
        v2_error(409, str(exc))
    return PendingDecisionV2.from_decision(resolved)


__all__ = [
    "PendingDecisionListV2",
    "PendingDecisionV2",
    "ResolveDecisionRequestV2",
    "get_orchestrator_v2",
    "list_pending_decisions_v2",
    "resolve_decision_v2",
    "router",
]
