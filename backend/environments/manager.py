"""Environment lifecycle orchestration (E32-S3/S4): provision -> execute -> collect -> teardown.

:class:`EnvironmentManager` is the single place that ties the backend
registry (E32-S1), the fail-closed policy checks (E32-S2), the durable
store, artifact egress, and audit events together. Mirrors
:class:`backend.execution.decisions.DecisionService`'s lazy-sweep pattern
for orphan reaping.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from backend.artifacts.pointers import ArtifactPointerStore, persist_artifact
from backend.artifacts.store import ArtifactKind, ArtifactStore, get_artifact_store
from backend.config.settings import Settings, get_settings
from backend.environments.contracts import (
    EnvironmentBackend,
    EnvironmentBackendError,
    EnvironmentBackendKind,
    EnvironmentDenial,
    EnvironmentHandle,
    EnvironmentProfile,
)
from backend.environments.policy import evaluate_filesystem_access
from backend.environments.registry import resolve_backend
from backend.environments.store import EnvironmentDecisionRecord, EnvironmentRecord, EnvironmentStore
from backend.events.runtime import emit_event
from backend.execution.contracts import ExecutionResult
from backend.quotas.contracts import QuotaExceededError

logger = logging.getLogger(__name__)


def _now() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat()


class EnvironmentCapacityExceededError(RuntimeError):
    """Raised when a tenant is already at its concurrent-environment ceiling."""

    def __init__(self, tenant_id: str, limit: int) -> None:
        """Build the error for a tenant at capacity.

        Args:
            tenant_id: Tenant that is at capacity.
            limit: The tenant's configured concurrent-environment ceiling.
        """
        super().__init__(
            f"tenant {tenant_id!r} already has {limit} active execution environments"
        )
        self.tenant_id = tenant_id
        self.limit = limit


class EnvironmentManager:
    """Orchestrates the provision -> execute -> collect -> teardown lifecycle."""

    def __init__(
        self,
        *,
        store: Optional[EnvironmentStore] = None,
        settings: Optional[Settings] = None,
        artifact_store: Optional[ArtifactStore] = None,
        artifact_pointers: Optional[ArtifactPointerStore] = None,
        backend_override: Optional[tuple[EnvironmentBackendKind, EnvironmentBackend]] = None,
    ) -> None:
        """Build the manager over a store and settings snapshot.

        Args:
            store: Durable environment store; defaults to a fresh
                :class:`~backend.environments.store.EnvironmentStore`.
            settings: Application settings; defaults to the cached settings.
            artifact_store: Object store for artifact egress; defaults to
                :func:`~backend.artifacts.store.get_artifact_store`.
            artifact_pointers: Pointer registry for artifact egress;
                defaults to a fresh
                :class:`~backend.artifacts.pointers.ArtifactPointerStore`.
            backend_override: Explicit ``(kind, backend)`` pair, bypassing
                :func:`~backend.environments.registry.resolve_backend`
                (tests only; production always resolves from configuration).
        """
        self._store = store or EnvironmentStore()
        self._settings = settings or get_settings()
        # Resolved lazily (see _resolve_artifact_store/_resolve_artifact_pointers):
        # touching the configured artifact backend (e.g. creating
        # AUTODEV_ARTIFACT_DIR) is real I/O that should only happen when
        # collect_artifacts() is actually called, not on every
        # EnvironmentManager() construction (most callers -- including
        # every OrchestratorService() built without an explicit run --
        # never provision an environment).
        self._explicit_artifact_store = artifact_store
        self._explicit_artifact_pointers = artifact_pointers
        self._artifact_store: Optional[ArtifactStore] = artifact_store
        self._artifact_pointers: Optional[ArtifactPointerStore] = artifact_pointers
        self._backend_kind, self._backend = backend_override or resolve_backend(self._settings)

    def _resolve_artifact_store(self) -> ArtifactStore:
        if self._artifact_store is None:
            self._artifact_store = self._explicit_artifact_store or get_artifact_store(self._settings)
        return self._artifact_store

    def _resolve_artifact_pointers(self) -> ArtifactPointerStore:
        if self._artifact_pointers is None:
            self._artifact_pointers = self._explicit_artifact_pointers or ArtifactPointerStore()
        return self._artifact_pointers

    def provision(
        self,
        *,
        run_id: str,
        tenant_id: str,
        workspace_ref: str,
        profile: Optional[EnvironmentProfile] = None,
    ) -> EnvironmentHandle:
        """Provision a new environment for *run_id* and return its handle.

        Reaps any of the tenant's orphaned environments first (lazy sweep,
        mirroring :class:`~backend.execution.decisions.DecisionService`),
        then admits the request against the tenant's concurrent-environment
        ceiling, then delegates provisioning to the resolved backend.

        Args:
            run_id: Orchestrator run this environment is provisioned for.
            tenant_id: Tenant the run belongs to.
            workspace_ref: Path to mount as the environment's workspace.
            profile: Explicit environment profile; defaults to
                :class:`~backend.environments.contracts.EnvironmentProfile`'s
                defaults.

        Returns:
            The provisioned environment's handle.

        Raises:
            EnvironmentCapacityExceededError: If the tenant is already at
                its concurrent-environment ceiling.
            EnvironmentBackendError: If the resolved backend cannot honor
                the profile (e.g. an unrecognized backend, or an
                unenforceable network policy).
        """
        self.reap_orphans()
        active_profile = profile or EnvironmentProfile()
        limit = self._settings.autodev_environment_max_concurrent
        if self._store.count_active(tenant_id) >= limit:
            raise EnvironmentCapacityExceededError(tenant_id, limit)

        handle = self._backend.provision(
            run_id=run_id, tenant_id=tenant_id, profile=active_profile, workspace_ref=workspace_ref
        )
        created_at = _now()
        ttl = self._settings.autodev_environment_ttl_seconds
        expires_iso = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
        self._store.create_environment(
            EnvironmentRecord(
                environment_id=handle.environment_id,
                run_id=run_id,
                tenant_id=tenant_id,
                backend_kind=handle.backend_kind.value,
                profile_id=active_profile.profile_id,
                profile_hash=active_profile.content_hash(),
                workspace_path=str(handle.workspace_path),
                status="active",
                created_at=created_at,
                expires_at=expires_iso,
            )
        )
        emit_event(
            "environment.instance.provisioned",
            tenant_id=tenant_id,
            partition_key=run_id,
            data={
                "environmentId": handle.environment_id,
                "backendKind": handle.backend_kind.value,
                "profileId": active_profile.profile_id,
                "profileHash": active_profile.content_hash(),
            },
            subject={"runId": run_id, "environmentId": handle.environment_id},
        )
        return handle

    def command_sandbox(self, handle: EnvironmentHandle):  # type: ignore[no-untyped-def]
        """Return the backend's ``SandboxRunner``-compatible object for *handle*.

        Used by :class:`~backend.execution.runner.CompositeActionRunner`
        (E32-S1-T1) so ``run_command``/``run_validation`` actions dispatch
        through the environment-scoped sandbox rather than a bare default.
        """
        return self._backend.command_sandbox(handle)

    def evaluate_filesystem(self, handle: EnvironmentHandle, *, path: str) -> Optional[EnvironmentDenial]:
        """Check and durably audit a filesystem access against *handle*'s policy.

        Args:
            handle: The provisioned environment the access targets.
            path: Candidate path, absolute or relative to the workspace.

        Returns:
            The denial, if the access is not permitted; ``None`` otherwise.
            Always durably recorded and always emits
            ``environment.access.allowed``/``.denied``.
        """
        denial = evaluate_filesystem_access(
            handle.profile, path=path, workspace_root=handle.workspace_path
        )
        allowed = denial is None
        reason = denial.reason if denial is not None else "workspace-scoped path"
        self._store.record_decision(
            EnvironmentDecisionRecord(
                decision_id=f"envdec_{uuid4().hex}",
                environment_id=handle.environment_id,
                run_id=handle.run_id,
                tenant_id=handle.tenant_id,
                category="filesystem",
                target=path,
                allowed=allowed,
                reason=reason,
                decided_at=_now(),
            )
        )
        emit_event(
            "environment.access.allowed" if allowed else "environment.access.denied",
            tenant_id=handle.tenant_id,
            partition_key=handle.run_id,
            data={
                "environmentId": handle.environment_id,
                "category": "filesystem",
                "target": path,
                "reason": reason,
            },
            subject={"runId": handle.run_id, "environmentId": handle.environment_id},
        )
        return denial

    def collect_artifacts(
        self, handle: EnvironmentHandle, results: list[ExecutionResult]
    ) -> list[str]:
        """Egress declared outputs (stdout/stderr/diff) via the artifact store.

        Only what each :class:`~backend.execution.contracts.ExecutionResult`
        declares leaves the environment -- nothing else is read back from
        the workspace mount.

        Args:
            handle: The environment the results came from.
            results: The action results produced during this environment's
                lifetime.

        Returns:
            The object keys of every artifact successfully persisted.
            Egress is best-effort: a store failure (e.g. an unwritable
            ``AUTODEV_ARTIFACT_DIR`` in a local/dev environment) is logged
            and skipped rather than failing the run -- evidence durability
            does not gate task execution.
        """
        if not results:
            return []
        try:
            artifact_store = self._resolve_artifact_store()
            artifact_pointers = self._resolve_artifact_pointers()
        except (OSError, QuotaExceededError):
            logger.warning(
                "environment %s: artifact store unavailable, skipping egress for run %s",
                handle.environment_id,
                handle.run_id,
            )
            return []
        object_keys: list[str] = []
        for result in results:
            if result.stdout or result.stderr:
                transcript = f"$ (exit {result.exit_code})\n{result.stdout}\n--- stderr ---\n{result.stderr}"
                key = f"{handle.tenant_id}/environments/{handle.environment_id}/{result.action_id}.log"
                if self._try_persist(
                    artifact_store,
                    artifact_pointers,
                    kind=ArtifactKind.LOG,
                    key=key,
                    payload=transcript.encode("utf-8"),
                    content_type="text/plain",
                    handle=handle,
                ):
                    object_keys.append(key)
            if result.diff:
                key = f"{handle.tenant_id}/environments/{handle.environment_id}/{result.action_id}.diff"
                if self._try_persist(
                    artifact_store,
                    artifact_pointers,
                    kind=ArtifactKind.RUN_EXPORT,
                    key=key,
                    payload=result.diff.encode("utf-8"),
                    content_type="text/x-diff",
                    handle=handle,
                ):
                    object_keys.append(key)
        return object_keys

    def _try_persist(
        self,
        artifact_store: ArtifactStore,
        artifact_pointers: ArtifactPointerStore,
        *,
        kind: ArtifactKind,
        key: str,
        payload: bytes,
        content_type: str,
        handle: EnvironmentHandle,
    ) -> bool:
        """Persist one artifact, returning whether it succeeded (best-effort egress)."""
        try:
            persist_artifact(
                artifact_store,
                artifact_pointers,
                kind=kind,
                object_key=key,
                payload=payload,
                content_type=content_type,
                tenant_id=handle.tenant_id,
                context={"environmentId": handle.environment_id, "runId": handle.run_id},
            )
        except (OSError, QuotaExceededError):
            logger.warning("environment %s: failed to persist artifact %s", handle.environment_id, key)
            return False
        return True

    def teardown(self, handle: EnvironmentHandle, *, reason: str = "completed") -> None:
        """Tear down a provisioned environment and mark its record terminal.

        Safe to call more than once for the same handle (idempotent from
        the caller's perspective; the underlying store update is a no-op
        once already terminal).

        Args:
            handle: The environment to tear down.
            reason: Human-readable teardown reason (``"completed"``,
                ``"failed"``, or ``"orphan_reaped"``).
        """
        self._backend.teardown(handle)
        self._store.mark_status(
            handle.environment_id,
            status="torn_down" if reason != "orphan_reaped" else "orphaned",
            torn_down_at=_now(),
        )
        emit_event(
            "environment.instance.retired",
            tenant_id=handle.tenant_id,
            partition_key=handle.run_id,
            data={"environmentId": handle.environment_id, "reason": reason},
            subject={"runId": handle.run_id, "environmentId": handle.environment_id},
        )

    def reap_orphans(self, *, at: Optional[str] = None) -> int:
        """Tear down and mark orphaned every active environment past its TTL.

        Args:
            at: ISO-8601 cutoff; defaults to now.

        Returns:
            The number of environments reaped.
        """
        cutoff = at or _now()
        expired = self._store.list_expired_active(before=cutoff)
        for record in expired:
            handle = EnvironmentHandle(
                environment_id=record.environment_id,
                run_id=record.run_id,
                tenant_id=record.tenant_id,
                profile=EnvironmentProfile(profile_id=record.profile_id),
                backend_kind=EnvironmentBackendKind(record.backend_kind),
                workspace_path=Path(record.workspace_path),
            )
            try:
                self.teardown(handle, reason="orphan_reaped")
            except EnvironmentBackendError:
                # Best-effort: the record is still marked orphaned below via
                # the store update inside teardown()'s own mark_status call
                # not having run -- fall back to a direct status flip.
                self._store.mark_status(record.environment_id, status="orphaned", torn_down_at=_now())
        return len(expired)

    def list_for_run(self, run_id: str) -> list[EnvironmentRecord]:
        """List every environment record provisioned for one run (audit, E32-S4-T1)."""
        return self._store.list_for_run(run_id)

    def list_decisions_for_run(self, run_id: str):  # type: ignore[no-untyped-def]
        """List every policy decision recorded for one run's environments (audit)."""
        return self._store.list_decisions_for_run(run_id)


__all__ = ["EnvironmentCapacityExceededError", "EnvironmentManager"]
