"""Isolation backend implementations behind the E32 abstraction (ADR-013).

``HardenedContainerBackend`` is the Beta default (ADR-013's recommendation):
it provisions the existing hardened Docker substrate
(:mod:`backend.validation.sandbox`), varying only the fields an
:class:`~backend.environments.contracts.EnvironmentProfile` actually
governs (network policy, workspace root). Per-profile CPU/memory/pids
overrides are captured in the profile and carried into every execution
record as evidence (E32-S4), but Beta's backend does not yet vary the
container's resource flags beyond ``SandboxRunner``'s existing hardened
defaults -- widening that is E28 scope, not a Beta contract change.

``UnavailableBackend`` is the fail-closed sentinel: every call denies. It
is both the second implementation proving the abstraction is truly
backend-agnostic (ADR-013's own stated plan) and the resolution target for
an unrecognized backend configuration (E32-S1-T2).
"""

from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path

from backend.environments.contracts import (
    EnvironmentBackendError,
    EnvironmentBackendKind,
    EnvironmentHandle,
    EnvironmentProfile,
)
from backend.environments.policy import evaluate_network_provisioning
from backend.validation.sandbox import SandboxPolicy, SandboxRunner, sandbox_policy_from_settings


class HardenedContainerBackend:
    """Beta default backend: hardened Docker via the existing ``SandboxRunner``."""

    def provision(
        self, *, run_id: str, tenant_id: str, profile: EnvironmentProfile, workspace_ref: str
    ) -> EnvironmentHandle:
        """Provision a hardened-container environment for *profile*.

        Args:
            run_id: Orchestrator run this environment is provisioned for.
            tenant_id: Tenant the run belongs to.
            profile: The resolved environment profile.
            workspace_ref: Absolute or resolvable path to mount as the
                environment's workspace.

        Returns:
            The provisioned environment's handle.

        Raises:
            EnvironmentBackendError: If *profile*'s network policy cannot
                be mechanically enforced by this backend (E32-S2-T1).
        """
        denial = evaluate_network_provisioning(profile)
        if denial is not None:
            raise EnvironmentBackendError(denial.reason)
        workspace_path = Path(workspace_ref).expanduser().resolve()
        return EnvironmentHandle(
            environment_id=f"env_{uuid.uuid4().hex}",
            run_id=run_id,
            tenant_id=tenant_id,
            profile=profile,
            backend_kind=EnvironmentBackendKind.HARDENED_CONTAINER,
            workspace_path=workspace_path,
        )

    def command_sandbox(self, handle: EnvironmentHandle) -> SandboxRunner:
        """Return a :class:`SandboxRunner` scoped to *handle*'s profile and workspace.

        Whether sandboxed execution runs at all is still governed by the
        operator's ``AUTODEV_ENABLE_SANDBOX``/``AUTODEV_SANDBOX_ALLOW_LOCAL``
        settings (:func:`~backend.validation.sandbox.sandbox_policy_from_settings`)
        -- an E32 environment binding scopes network policy and the
        workspace root, it does not itself force sandboxed execution on
        for a deployment that has not opted in.
        """
        base = sandbox_policy_from_settings()
        docker_network = "none" if handle.profile.network_policy.deny_all else base.docker_network
        policy = dataclasses.replace(
            base, docker_network=docker_network, project_root=handle.workspace_path
        )
        return SandboxRunner(policy=policy)

    def teardown(self, handle: EnvironmentHandle) -> None:
        """No persistent backend-side state to release (per-command containers)."""
        return None


class UnavailableBackend:
    """Fail-closed sentinel backend: every operation denies.

    Selected when the configured backend name is unrecognized -- a typo in
    ``AUTODEV_EXECUTION_ENVIRONMENT_BACKEND`` fails closed rather than
    silently falling back to a working-but-unintended backend.
    """

    def provision(
        self, *, run_id: str, tenant_id: str, profile: EnvironmentProfile, workspace_ref: str
    ) -> EnvironmentHandle:
        """Always raise: this backend never provisions a working environment."""
        raise EnvironmentBackendError(
            "execution environment backend is unavailable (unrecognized or "
            "unresolved configuration) -- fails closed rather than "
            "silently selecting a different backend"
        )

    def command_sandbox(self, handle: EnvironmentHandle) -> SandboxRunner:
        """Return a permanently disabled sandbox (defense in depth; provision() already denies)."""
        return SandboxRunner(policy=SandboxPolicy(
            enabled=False,
            allow_local=False,
            docker_network="none",
            project_root=handle.workspace_path,
            timeout_seconds=1,
        ))

    def teardown(self, handle: EnvironmentHandle) -> None:
        """No-op: this backend never holds provisioned state."""
        return None


__all__ = ["HardenedContainerBackend", "UnavailableBackend"]
