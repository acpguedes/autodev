"""Canonical role matrix, legacy alias normalization, and scope narrowing.

The grant matrix below is the executable form of ADR-018's capability table
(``docs/v2_platform/decisions/ADR-018-control-plane-authentication-rbac-audit.md``).
Each role's grant set is defined as an addition on top of the role below it,
so the cumulative hierarchy (``viewer < operator < maintainer < admin <
owner``) can never silently drift out of sync between the two roles.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from backend.auth.contracts import Role

# Legacy §14.2 spelling accepted on ingestion only; never emitted or persisted.
_LEGACY_ROLE_ALIASES: dict[str, Role] = {"author": Role.MAINTAINER}

_SCOPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")

# Additive grants per role, applied cumulatively in this tier order.
_ROLE_TIER_ADDITIONS: tuple[tuple[Role, frozenset[str]], ...] = (
    (
        Role.VIEWER,
        frozenset(
            {
                "auth:self",
                "session:read",
                "run:read",
                "flow:read",
                "agent:read",
                "skill:read",
                "plan:read",
                "plugin:read",
                "config:read_redacted",
                "quota:read",
            }
        ),
    ),
    (
        Role.OPERATOR,
        frozenset({"session:write", "run:write", "run:cancel"}),
    ),
    (
        Role.MAINTAINER,
        frozenset(
            {
                "flow:write",
                "flow:execute",
                "agent:write",
                "agent:invoke",
                "skill:write",
                "skill:invoke",
                "plan:write",
                "plan:approve",
                "patch:propose",
                "patch:review",
                "patch:apply",
                "mcp:invoke",
            }
        ),
    ),
    (
        Role.ADMIN,
        frozenset(
            {
                "plugin:admin",
                "config:write_safe",
                "config:admin",
                "quota:admin",
                "audit:read",
                "service_credential:admin",
                "rbac:admin",
            }
        ),
    ),
    (
        Role.OWNER,
        frozenset({"tenant:owner"}),
    ),
)


def _build_role_grants() -> dict[Role, frozenset[str]]:
    """Materialize each role's cumulative scope grant from the tier additions.

    Returns:
        A mapping from role to its full, cumulative scope grant.
    """
    grants: dict[Role, frozenset[str]] = {}
    accumulated: frozenset[str] = frozenset()
    for role, additions in _ROLE_TIER_ADDITIONS:
        accumulated = accumulated | additions
        grants[role] = accumulated
    return grants


ROLE_GRANTS: dict[Role, frozenset[str]] = _build_role_grants()

# Every scope any role can grant — the closed vocabulary asserted scopes and
# service-credential scope requests are validated against.
ALL_KNOWN_SCOPES: frozenset[str] = frozenset(
    scope for grants in ROLE_GRANTS.values() for scope in grants
)


def normalize_role(value: str) -> Role:
    """Normalize a role string to its canonical :class:`Role`.

    Accepts the legacy ``author`` alias (normalizes to
    :attr:`Role.MAINTAINER`) in addition to the five canonical spellings.

    Args:
        value: Candidate role string, as received from a claim, config
            file, or CLI argument.

    Returns:
        The canonical :class:`Role`.

    Raises:
        ValueError: If ``value`` is not a recognized role or legacy alias.
    """
    normalized = value.strip().lower()
    alias = _LEGACY_ROLE_ALIASES.get(normalized)
    if alias is not None:
        return alias
    try:
        return Role(normalized)
    except ValueError:
        raise ValueError(f"Unknown role: {value!r}") from None


def normalize_scopes(value: str | Sequence[str]) -> frozenset[str]:
    """Parse and validate a scope string or sequence into a frozen scope set.

    Args:
        value: Either a whitespace-separated scope string (as found in an
            OIDC ``scope`` claim) or a sequence of scope strings.

    Returns:
        The parsed, validated scopes.

    Raises:
        ValueError: If any scope does not match ``^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$``.
    """
    raw = value.split() if isinstance(value, str) else list(value)
    scopes = frozenset(item.strip() for item in raw if item.strip())
    invalid = sorted(scope for scope in scopes if not _SCOPE_PATTERN.fullmatch(scope))
    if invalid:
        raise ValueError(f"Invalid scope(s): {', '.join(invalid)}")
    return scopes


def effective_scopes(
    roles: tuple[Role, ...], asserted_scopes: frozenset[str] | None
) -> frozenset[str]:
    """Compute a principal's effective scopes from its roles and assertions.

    Role grants are the maximum a principal may hold. An explicit
    ``asserted_scopes`` set (e.g. a service key minted with a reduced scope
    list) can only narrow that maximum, never widen it.

    Args:
        roles: The principal's canonical roles.
        asserted_scopes: Explicitly asserted scopes, or ``None``/empty to use
            the full grant of ``roles`` unnarrowed.

    Returns:
        The principal's effective, narrowed scope set.
    """
    granted: frozenset[str] = frozenset()
    for role in roles:
        granted = granted | ROLE_GRANTS.get(role, frozenset())
    if not asserted_scopes:
        return granted
    return granted & asserted_scopes


__all__ = [
    "ALL_KNOWN_SCOPES",
    "ROLE_GRANTS",
    "effective_scopes",
    "normalize_role",
    "normalize_scopes",
]
