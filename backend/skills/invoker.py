"""Least-privilege skill invocation broker for the Agent Runtime (E6-S3)."""

from __future__ import annotations

import importlib
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.plugins.events import PluginEvent
from backend.plugins.permissions import PermissionBroker
from backend.skills.manifest import SkillManifest, validate_io
from backend.skills.registry_v2 import SkillRegistry


class SkillInvocationDenied(PermissionError):
    """Raised when a skill invocation is denied for a permission or IO reason."""


class SkillBudgetExceeded(RuntimeError):
    """Raised when a skill invocation exceeds its declared execution budget."""


@dataclass(frozen=True)
class _SkillPermissionGrant:
    """Adapts a flat :class:`SkillPermissions` declaration into ``PermissionBroker`` grants."""

    filesystem_read: tuple[str, ...] = ()
    filesystem_write: tuple[str, ...] = ()
    network_egress: tuple[str, ...] = ()
    exec_commands: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()


@dataclass(frozen=True)
class _SkillManifestShim:
    """Minimal manifest-shaped object satisfying ``PermissionBroker``'s duck-typed interface."""

    id: str
    permissions: _SkillPermissionGrant = field(default_factory=_SkillPermissionGrant)


def _permission_broker_for(manifest: SkillManifest, workspace: Path) -> PermissionBroker:
    """Build a :class:`PermissionBroker` for a skill's flat permission declaration.

    Reuses the plugin permission broker verbatim rather than reimplementing
    path-guard/import-sandbox enforcement: a skill's coarse ``none``/``read``/
    ``read-write`` filesystem level and ``none``/``allow`` network level are
    translated into the broker's granular grant tuples, scoped to ``workspace``.

    Args:
        manifest: The skill manifest declaring the permission level.
        workspace: Root directory the skill is allowed to read/write within.

    Returns:
        A :class:`PermissionBroker` enforcing the skill's declared grants.
    """
    perms = manifest.permissions
    grant = _SkillPermissionGrant(
        filesystem_read=("${workspace}",) if perms.filesystem in ("read", "read-write") else (),
        filesystem_write=("${workspace}",) if perms.filesystem == "read-write" else (),
        network_egress=("*",) if perms.network == "allow" else (),
    )
    shim = _SkillManifestShim(id=manifest.id, permissions=grant)
    return PermissionBroker(shim, workspace=workspace)  # type: ignore[arg-type]


class SkillInvocationBroker:
    """Resolves, permission-checks, budgets, and invokes skills via the Skill Registry."""

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        workspace: Path,
        event_sink: Callable[[PluginEvent], None] | None = None,
    ) -> None:
        """Initialize the broker.

        Args:
            registry: Skill Registry used to resolve skill manifests.
            workspace: Root directory skills with filesystem access are scoped to.
            event_sink: Callback invoked with a :class:`PluginEvent` on each invocation.
        """
        self._registry = registry
        self._workspace = workspace
        self._event_sink = event_sink

    def invoke(self, skill_id: str, version_range: str = "*", **kwargs: Any) -> Any:
        """Resolve, validate, budget-enforce, and invoke a skill.

        Args:
            skill_id: Fully qualified skill id to invoke.
            version_range: SemVer range expression selecting the version.
            **kwargs: Input payload forwarded to the skill's entrypoint.

        Returns:
            The skill's validated output payload.

        Raises:
            SkillInvocationDenied: If the skill cannot be resolved or IO is invalid.
            SkillBudgetExceeded: If the invocation exceeds its declared timeout.
        """
        try:
            ref = self._registry.resolve(skill_id, version_range)
        except KeyError as exc:
            self._emit("skill.invocation.denied", skill_id, {"reason": "not-found"})
            raise SkillInvocationDenied(str(exc)) from exc

        manifest = ref.manifest
        input_errors = validate_io(manifest.io_input, kwargs)
        if input_errors:
            self._emit("skill.invocation.denied", skill_id, {"reason": "invalid-input", "errors": input_errors})
            raise SkillInvocationDenied(f"invalid input for {skill_id}: {'; '.join(input_errors)}")

        permission_broker = _permission_broker_for(manifest, self._workspace)
        entrypoint = self._load_entrypoint(manifest.entrypoint)

        started = time.perf_counter()
        try:
            with permission_broker.import_sandbox():
                output = self._run_with_timeout(entrypoint, kwargs, manifest)
        except FutureTimeoutError as exc:
            self._emit("skill.invocation.denied", skill_id, {"reason": "budget-exceeded"})
            raise SkillBudgetExceeded(
                f"{skill_id} exceeded its {manifest.budgets.timeout_sec}s timeout budget"
            ) from exc

        output_errors = validate_io(manifest.io_output, output)
        if output_errors:
            self._emit("skill.invocation.denied", skill_id, {"reason": "invalid-output", "errors": output_errors})
            raise SkillInvocationDenied(f"invalid output from {skill_id}: {'; '.join(output_errors)}")

        elapsed_ms = (time.perf_counter() - started) * 1000
        self._emit(
            "skill.invocation.completed",
            skill_id,
            {"version": ref.version, "elapsedMs": elapsed_ms},
        )
        return output

    def _run_with_timeout(
        self, entrypoint: Callable[..., dict[str, Any]], kwargs: dict[str, Any], manifest: SkillManifest
    ) -> dict[str, Any]:
        """Run a skill entrypoint under its declared wall-clock timeout budget."""
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(entrypoint, **kwargs)
            return future.result(timeout=manifest.budgets.timeout_sec)

    def _load_entrypoint(self, entrypoint: str) -> Callable[..., Any]:
        """Import a ``module:function`` entrypoint reference.

        Raises:
            SkillInvocationDenied: If the module or attribute cannot be loaded.
        """
        module_name, _, attr = entrypoint.partition(":")
        try:
            module = importlib.import_module(module_name)
            return getattr(module, attr)
        except (ImportError, AttributeError) as exc:
            raise SkillInvocationDenied(f"cannot load entrypoint {entrypoint!r}: {exc}") from exc

    def _emit(self, name: str, skill_id: str, payload: dict[str, Any]) -> None:
        """Emit a call-trace event, if an event sink is configured."""
        if self._event_sink is not None:
            self._event_sink(PluginEvent(name=name, plugin_id=skill_id, payload=payload))


__all__ = ["SkillBudgetExceeded", "SkillInvocationBroker", "SkillInvocationDenied"]
