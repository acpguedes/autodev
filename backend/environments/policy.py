"""Fail-closed network/filesystem policy checks for provisioned environments (E32-S2).

Pure, side-effect-free evaluation functions. Audit recording and event
emission are the caller's responsibility (:class:`backend.environments.manager.EnvironmentManager`)
so these can be unit tested without a store or event bus.
"""

from __future__ import annotations

from pathlib import Path

from backend.environments.contracts import EnvironmentDenial, EnvironmentProfile


def evaluate_network_provisioning(profile: EnvironmentProfile) -> EnvironmentDenial | None:
    """Check whether *profile*'s network policy can be honored at provisioning time.

    Beta's ``HARDENED_CONTAINER`` backend enforces only a binary
    default-deny (no egress proxy or DNS-level allowlist yet -- E28
    scope). A profile that declares ``deny_all=False`` with a non-empty
    allowlist is therefore unenforceable as declared: rather than silently
    granting full network access (broader than promised) or silently
    ignoring the allowlist (narrower than promised), provisioning fails
    closed.

    Args:
        profile: The environment profile about to be provisioned.

    Returns:
        A denial if the declared policy cannot be mechanically enforced;
        ``None`` if provisioning may proceed.
    """
    if profile.network_policy.deny_all:
        return None
    if not profile.network_policy.allowlist:
        # deny_all=False with an empty allowlist is an explicit "allow all"
        # request; a self-hoster with a documented threat model may still
        # provision it deliberately (the ADR-013 hardened-container
        # backend's docker_network override).
        return None
    return EnvironmentDenial(
        category="network",
        target=",".join(profile.network_policy.allowlist),
        reason=(
            "profile declares a network egress allowlist, but the resolved "
            "backend cannot enforce a fine-grained allowlist (Beta scope); "
            "provisioning denied rather than granting broader or narrower "
            "access than declared"
        ),
    )


def evaluate_filesystem_access(
    profile: EnvironmentProfile, *, path: str, workspace_root: Path
) -> EnvironmentDenial | None:
    """Check whether *path* is reachable under *profile*'s filesystem policy.

    Args:
        profile: The environment profile governing this access.
        path: Candidate path, absolute or relative to *workspace_root*.
        workspace_root: The environment's workspace mount root.

    Returns:
        A denial if *path* escapes the workspace mount while
        ``workspace_only`` is set; ``None`` if the access is permitted.
    """
    if not profile.filesystem_policy.workspace_only:
        return None
    resolved_root = workspace_root.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = resolved_root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return EnvironmentDenial(
            category="filesystem",
            target=path,
            reason=f"path {path!r} resolves outside the workspace mount {resolved_root}",
        )
    return None


__all__ = ["evaluate_filesystem_access", "evaluate_network_provisioning"]
