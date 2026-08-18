"""Backend selection by configuration only (E32-S1-T2, ADR-013).

Callers never name a backend directly -- ``resolve_backend`` is the single
place configuration maps to an :class:`~backend.environments.contracts.EnvironmentBackend`
instance. An unset value resolves to the Beta default
(``hardened_container``); an unrecognized value resolves to the fail-closed
``unavailable`` sentinel rather than silently choosing a working backend
the operator did not ask for.
"""

from __future__ import annotations

from backend.config.settings import Settings, get_settings
from backend.environments.backends import HardenedContainerBackend, UnavailableBackend
from backend.environments.contracts import EnvironmentBackend, EnvironmentBackendKind

_BACKENDS: dict[EnvironmentBackendKind, EnvironmentBackend] = {
    EnvironmentBackendKind.HARDENED_CONTAINER: HardenedContainerBackend(),
    EnvironmentBackendKind.UNAVAILABLE: UnavailableBackend(),
}


def resolve_backend(
    settings: Settings | None = None,
) -> tuple[EnvironmentBackendKind, EnvironmentBackend]:
    """Resolve the configured execution-environment backend.

    Args:
        settings: Application settings; defaults to the cached settings.

    Returns:
        The resolved backend kind and its instance. Unset configuration
        resolves to ``HARDENED_CONTAINER`` (the Beta default); an
        unrecognized value resolves to ``UNAVAILABLE`` (fail-closed).
    """
    active = settings or get_settings()
    raw = active.autodev_execution_environment_backend.strip().lower()
    if not raw:
        kind = EnvironmentBackendKind.HARDENED_CONTAINER
    else:
        try:
            kind = EnvironmentBackendKind(raw)
        except ValueError:
            kind = EnvironmentBackendKind.UNAVAILABLE
    return kind, _BACKENDS[kind]


__all__ = ["resolve_backend"]
