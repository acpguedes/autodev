"""Execution-environment lifecycle scope for one task-dispatch batch (E32, E47-S5-T1).

Extracted out of ``task_dispatch._process_tasks`` so provision/bind/collect/
teardown is one small, independently testable unit instead of interleaved
with per-task dispatch control flow.
"""

from __future__ import annotations

from typing import List, Optional

from backend.environments.contracts import EnvironmentBackendError, EnvironmentHandle
from backend.environments.manager import EnvironmentCapacityExceededError, EnvironmentManager
from backend.execution.contracts import ExecutionResult
from backend.execution.runner import InProcessActionRunner


class ExecutionEnvironmentScope:
    """Owns provision/bind/collect/teardown for one dispatch batch's E32 environment.

    A provisioning failure (capacity ceiling or backend error) is captured
    as :attr:`denied_reason` rather than raised: the caller denies every
    action in the batch through the normal policy path instead of silently
    falling back to unisolated execution (E32-S3/S4 fail-closed).
    """

    def __init__(
        self,
        environment_manager: EnvironmentManager,
        composite_runner: InProcessActionRunner,
    ) -> None:
        self._environment_manager = environment_manager
        self._composite_runner = composite_runner
        self.handle: Optional[EnvironmentHandle] = None
        self.denied_reason: Optional[str] = None

    def provision(self, *, run_id: str, tenant_id: str, workspace_ref: str) -> None:
        """Provision and bind the batch's environment, or record why it was denied."""
        try:
            self.handle = self._environment_manager.provision(
                run_id=run_id, tenant_id=tenant_id, workspace_ref=workspace_ref
            )
            self._composite_runner.bind_environment(self.handle)
        except (EnvironmentCapacityExceededError, EnvironmentBackendError) as exc:
            self.denied_reason = f"execution environment unavailable: {exc}"

    def teardown(self, action_results: List[ExecutionResult]) -> None:
        """Collect the batch's artifacts and tear down the environment, if one was provisioned.

        No-op when :meth:`provision` never obtained a handle (denied or the
        batch had nothing to dispatch).
        """
        if self.handle is not None:
            self._environment_manager.collect_artifacts(self.handle, action_results)
            self._environment_manager.teardown(self.handle)
            self._composite_runner.bind_environment(None)


__all__ = ["ExecutionEnvironmentScope"]
