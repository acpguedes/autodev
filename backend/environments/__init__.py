"""Execution-environment abstraction for the Beta cut (E32, RFC pending/ADR-013).

Owns *where* an :class:`~backend.execution.contracts.ExecutionAction` runs:
a pluggable, backend-agnostic environment profile with a fail-closed
network/filesystem policy and a governed provision -> execute -> collect ->
teardown lifecycle. E14 continues to own *what* runs.
"""

from backend.environments.contracts import (
    EnvironmentBackend,
    EnvironmentBackendError,
    EnvironmentBackendKind,
    EnvironmentDenial,
    EnvironmentHandle,
    EnvironmentProfile,
    FilesystemPolicy,
    NetworkPolicy,
)
from backend.environments.manager import EnvironmentManager
from backend.environments.registry import resolve_backend

__all__ = [
    "EnvironmentBackend",
    "EnvironmentBackendError",
    "EnvironmentBackendKind",
    "EnvironmentDenial",
    "EnvironmentHandle",
    "EnvironmentManager",
    "EnvironmentProfile",
    "FilesystemPolicy",
    "NetworkPolicy",
    "resolve_backend",
]
