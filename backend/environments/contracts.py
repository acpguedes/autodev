"""Contracts for the Beta execution-environment abstraction (E32-S1, ADR-013).

Defines the backend-agnostic :class:`EnvironmentProfile` and
:class:`EnvironmentBackend` protocol every isolation backend implements.
Callers never select a backend directly (E32-S1-T2): it is resolved from
configuration by :func:`backend.environments.registry.resolve_backend`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Fallback StrEnum compatible with Python 3.10."""

        pass


class EnvironmentBackendKind(StrEnum):
    """Isolation backends selectable behind the E32 abstraction (Beta cut).

    ``HARDENED_CONTAINER`` is the Beta default recommended by ADR-013 (the
    existing hardened Docker substrate). ``UNAVAILABLE`` is the fail-closed
    sentinel backend: it denies every provisioning request. It is both the
    second implementation proving the interface is backend-agnostic
    (ADR-013's own recommendation) and the resolution target for an
    unrecognized backend name, so a configuration typo fails closed instead
    of silently granting a weaker or unintended isolation guarantee.
    """

    HARDENED_CONTAINER = "hardened_container"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    """Declared network-egress policy for one :class:`EnvironmentProfile`.

    Attributes:
        deny_all: Default-deny egress (E32-S2-T1). ``True`` in every Beta
            default profile.
        allowlist: Hostnames/registries permitted when ``deny_all`` is
            ``False``. Beta's ``HARDENED_CONTAINER`` backend cannot enforce
            a fine-grained allowlist (no egress proxy yet -- deferred to
            E28); a profile that sets ``deny_all=False`` with a non-empty
            allowlist therefore fails closed at provisioning rather than
            silently granting broader access than declared. See
            ``docs/environments/beta_isolation.md``.
    """

    deny_all: bool = True
    allowlist: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FilesystemPolicy:
    """Declared filesystem-scope policy for one :class:`EnvironmentProfile`.

    Attributes:
        workspace_only: When ``True`` (the Beta default), only paths inside
            the provisioned workspace mount are reachable; host paths,
            sockets, and devices are denied.
        read_only_base: When ``True`` (the Beta default), the backend's
            base image/rootfs layer is mounted read-only.
    """

    workspace_only: bool = True
    read_only_base: bool = True


@dataclass(frozen=True, slots=True)
class EnvironmentProfile:
    """A declared environment profile (E32-S1-T1): base image, limits, policy.

    Attributes:
        profile_id: Stable identifier for this profile (e.g. ``"default"``).
        base_image: Base image/rootfs the backend provisions.
        cpu_limit: CPU core limit passed to the backend.
        memory_limit_mb: Memory limit, in megabytes.
        pids_limit: Maximum concurrent process count.
        network_policy: Fail-closed network-egress policy (E32-S2).
        filesystem_policy: Fail-closed filesystem-scope policy (E32-S2).
        env_allowlist: Environment variable names permitted to reach the
            environment; ambient credentials are denied unless named here.
    """

    profile_id: str = "default"
    base_image: str = "python:3.11-slim"
    cpu_limit: float = 1.0
    memory_limit_mb: int = 512
    pids_limit: int = 256
    network_policy: NetworkPolicy = field(default_factory=NetworkPolicy)
    filesystem_policy: FilesystemPolicy = field(default_factory=FilesystemPolicy)
    env_allowlist: tuple[str, ...] = ()

    def content_hash(self) -> str:
        """Return a stable SHA-256 hash of this profile's configuration.

        Included in every execution record as evidence (E32-S4-T2) so a
        gate can assert "ran isolated" from the resolved configuration
        rather than from a claim.
        """
        canonical = {
            "profile_id": self.profile_id,
            "base_image": self.base_image,
            "cpu_limit": self.cpu_limit,
            "memory_limit_mb": self.memory_limit_mb,
            "pids_limit": self.pids_limit,
            "network_policy": {
                "deny_all": self.network_policy.deny_all,
                "allowlist": list(self.network_policy.allowlist),
            },
            "filesystem_policy": {
                "workspace_only": self.filesystem_policy.workspace_only,
                "read_only_base": self.filesystem_policy.read_only_base,
            },
            "env_allowlist": list(self.env_allowlist),
        }
        payload = json.dumps(canonical, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class EnvironmentBackendError(RuntimeError):
    """Raised when a backend cannot provision or honor a requested profile."""


@dataclass(frozen=True, slots=True)
class EnvironmentDenial:
    """One typed, audited policy denial (E32-S2-T3).

    Attributes:
        category: ``"network"`` or ``"filesystem"``.
        target: The host or path the denied access targeted.
        reason: Human-readable reason, durably recorded and returned to callers.
    """

    category: str
    target: str
    reason: str


@dataclass(frozen=True, slots=True)
class EnvironmentHandle:
    """A provisioned environment instance, returned by :meth:`EnvironmentBackend.provision`.

    Attributes:
        environment_id: Unique identifier for this provisioned instance.
        run_id: Orchestrator run this environment was provisioned for.
        tenant_id: Tenant the run belongs to.
        profile: The resolved profile this instance was provisioned from.
        backend_kind: The backend that provisioned this instance.
        workspace_path: Absolute host path backing the environment's
            workspace mount.
    """

    environment_id: str
    run_id: str
    tenant_id: str
    profile: EnvironmentProfile
    backend_kind: EnvironmentBackendKind
    workspace_path: Path


class EnvironmentBackend(Protocol):
    """An isolation backend pluggable behind the E32 abstraction.

    Every backend implements the same four lifecycle operations
    (E32-S3-T1); callers never branch on which backend is active.
    """

    def provision(
        self, *, run_id: str, tenant_id: str, profile: EnvironmentProfile, workspace_ref: str
    ) -> EnvironmentHandle:
        """Provision a new environment instance for *profile* and return its handle.

        Raises:
            EnvironmentBackendError: If the backend cannot honor *profile*
                (e.g. an unenforceable network allowlist) -- fails closed
                rather than silently downgrading the policy.
        """
        ...

    def command_sandbox(self, handle: EnvironmentHandle):  # type: ignore[no-untyped-def]
        """Return a ``SandboxRunner``-compatible object scoped to *handle*."""
        ...

    def teardown(self, handle: EnvironmentHandle) -> None:
        """Tear down a previously provisioned environment instance."""
        ...


__all__ = [
    "EnvironmentBackend",
    "EnvironmentBackendError",
    "EnvironmentBackendKind",
    "EnvironmentDenial",
    "EnvironmentHandle",
    "EnvironmentProfile",
    "FilesystemPolicy",
    "NetworkPolicy",
]
