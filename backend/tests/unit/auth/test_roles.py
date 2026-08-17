"""Contracts for the canonical RBAC role/scope model (E11-S2 Task 1)."""

from __future__ import annotations

import pytest

from backend.auth.contracts import AuthMethod, PrincipalV2, Role
from backend.auth.roles import effective_scopes, normalize_role, normalize_scopes


def test_author_is_only_an_input_alias() -> None:
    """The legacy ``author`` spelling normalizes to the canonical maintainer role."""
    assert normalize_role("author") is Role.MAINTAINER
    assert normalize_role("maintainer") is Role.MAINTAINER


def test_author_is_never_emitted() -> None:
    """A principal built from a legacy alias only ever carries canonical roles."""
    principal = PrincipalV2(
        subject="user-1",
        tenant_id="tenant-a",
        roles=(normalize_role("author"),),
        scopes=frozenset({"flow:write"}),
        auth_method=AuthMethod.OIDC,
    )
    assert [role.value for role in principal.roles] == ["maintainer"]


def test_unknown_role_is_rejected() -> None:
    """An unrecognized role string is never silently accepted."""
    with pytest.raises(ValueError):
        normalize_role("superuser")


def test_normalize_scopes_accepts_string_or_sequence() -> None:
    """Scopes may be parsed from a space-separated string or a sequence."""
    assert normalize_scopes("run:read run:write") == frozenset({"run:read", "run:write"})
    assert normalize_scopes(["run:read", "run:write"]) == frozenset(
        {"run:read", "run:write"}
    )


def test_normalize_scopes_rejects_malformed_scope() -> None:
    """A scope string must match ``resource:action``."""
    with pytest.raises(ValueError):
        normalize_scopes("not-a-scope")


def test_asserted_scopes_only_narrow_role_grants() -> None:
    """Asserted scopes can subset but never exceed a role's grants."""
    result = effective_scopes(
        (Role.MAINTAINER,),
        frozenset({"run:read", "flow:write", "plugin:admin"}),
    )
    assert result == frozenset({"run:read", "flow:write"})


def test_no_asserted_scopes_returns_full_role_grant() -> None:
    """Omitting asserted scopes grants the role's full scope set."""
    viewer_scopes = effective_scopes((Role.VIEWER,), None)
    admin_scopes = effective_scopes((Role.ADMIN,), None)
    assert viewer_scopes < admin_scopes
    assert "run:read" in viewer_scopes
    assert "run:write" not in viewer_scopes
    assert "rbac:admin" in admin_scopes


def test_role_hierarchy_is_cumulative() -> None:
    """Each higher role grants a superset of the role below it."""
    viewer = effective_scopes((Role.VIEWER,), None)
    operator = effective_scopes((Role.OPERATOR,), None)
    maintainer = effective_scopes((Role.MAINTAINER,), None)
    admin = effective_scopes((Role.ADMIN,), None)
    owner = effective_scopes((Role.OWNER,), None)
    assert viewer < operator < maintainer < admin < owner


def test_owner_only_grant_is_tenant_transfer() -> None:
    """Only the owner role can transfer tenant ownership."""
    admin_scopes = effective_scopes((Role.ADMIN,), None)
    owner_scopes = effective_scopes((Role.OWNER,), None)
    assert "tenant:owner" not in admin_scopes
    assert "tenant:owner" in owner_scopes
