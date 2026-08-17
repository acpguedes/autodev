"""v2 Control Plane API — execution policy rules (E14-S2, RFC-010/ADR-022)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.api.authorization import requires_scope
from backend.api.rbac_v2 import PrincipalV2, require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2
from backend.execution.policy import PolicyCategory, PolicyEffect, PolicyRule, PolicyScopeKind, PolicyService

router = APIRouter(
    prefix="/v2/execution/policy", tags=["execution-policy"], dependencies=[Depends(require_v2_principal)]
)


def get_policy_service() -> PolicyService:
    """Build a :class:`PolicyService` bound to the shared durable store.

    Constructed fresh per request, matching every other ``/v2`` router's
    service-provider convention (see ``quotas_v2.get_quota_service``).

    Returns:
        A new :class:`PolicyService`.
    """
    return PolicyService()


class PolicyRuleV2(BaseModel):
    """One execution policy rule, as exposed over the API."""

    model_config = ConfigDict(populate_by_name=True)

    category: PolicyCategory
    effect: PolicyEffect
    scope_kind: PolicyScopeKind = Field(alias="scopeKind")
    scope_id: str = Field(alias="scopeId")
    pattern: str | None = None

    def to_rule(self) -> PolicyRule:
        """Convert this request/response model into its domain type."""
        return PolicyRule(
            category=self.category,
            effect=self.effect,
            scope_kind=self.scope_kind,
            scope_id=self.scope_id,
            pattern=self.pattern,
        )

    @classmethod
    def from_rule(cls, rule: PolicyRule) -> "PolicyRuleV2":
        """Build the API model from a domain :class:`PolicyRule`."""
        return cls(
            category=rule.category,
            effect=rule.effect,
            scopeKind=rule.scope_kind,
            scopeId=rule.scope_id,
            pattern=rule.pattern,
        )


class PolicyRuleListV2(BaseModel):
    """A tenant's effective execution policy rule set."""

    schemaVersion: str = SCHEMA_VERSION_V2
    rules: list[PolicyRuleV2]


@requires_scope("policy:read")
@router.get("", response_model=PolicyRuleListV2)
def list_execution_policy_v2(
    policy_service: PolicyService = Depends(get_policy_service),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> PolicyRuleListV2:
    """Return the caller's own tenant's effective execution policy rules.

    Args:
        policy_service: Policy service dependency.
        principal: Authenticated caller; its tenant is the only tenant this
            endpoint can ever query.

    Returns:
        The tenant's effective rule set (durably stored, or the local
        permissive default outside production).
    """
    rules = policy_service.resolve_rules(principal.tenant_id)
    return PolicyRuleListV2(rules=[PolicyRuleV2.from_rule(rule) for rule in rules])


@requires_scope("policy:admin")
@router.post("", response_model=PolicyRuleV2, status_code=201)
def add_execution_policy_rule_v2(
    request: PolicyRuleV2,
    policy_service: PolicyService = Depends(get_policy_service),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> PolicyRuleV2:
    """Durably add one execution policy rule for the caller's own tenant.

    Args:
        request: The rule to store.
        policy_service: Policy service dependency.
        principal: Authenticated caller (must hold ``policy:admin``); its
            tenant is the only tenant this endpoint can ever write.

    Returns:
        The stored rule.
    """
    policy_service.set_rule(principal.tenant_id, request.to_rule())
    return request


__all__ = [
    "PolicyRuleListV2",
    "PolicyRuleV2",
    "add_execution_policy_rule_v2",
    "get_policy_service",
    "list_execution_policy_v2",
    "router",
]
