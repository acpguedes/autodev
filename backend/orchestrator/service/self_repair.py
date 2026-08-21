"""Bounded, batched Coder self-repair over failed validation tasks (E41-S5, E46-S3, E47-S5)."""

from __future__ import annotations

from typing import Dict, List, Mapping

from backend.agents import AgentContext
from backend.orchestrator.service import events
from backend.execution.contracts import ExecutionAction, ExecutionActionType, ExecutionResult
from backend.execution.executor import TaskExecutionOutcome
from backend.execution.modes import ExecutionMode
from backend.orchestrator.service._shared import OrchestratorState
from backend.orchestrator.service.models import ExecutionTask


class SelfRepairMixin(OrchestratorState):
    """Single-task and batched self-repair over failed validation task outcomes."""

    def _maybe_self_repair(
        self,
        *,
        task: "ExecutionTask",
        validation_outcome: TaskExecutionOutcome,
        batch_results: List[ExecutionResult],
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode,
    ) -> tuple[TaskExecutionOutcome, str]:
        """Single-task convenience wrapper over :meth:`_maybe_batch_self_repair` (E41-S5, E46-S3).

        Kept as its own entry point since a caller with exactly one
        validation task (or a test exercising the repair policy in
        isolation) shouldn't have to build a one-element candidate list.
        ``task_dispatch._process_tasks`` itself calls
        :meth:`_maybe_batch_self_repair` directly so a batch with several
        failing validation tasks gets one Coder call, not one per task.
        """
        repaired = self._maybe_batch_self_repair(
            [(task, validation_outcome)],
            batch_results=batch_results,
            run_id=run_id,
            tenant_id=tenant_id,
            mode=mode,
        )
        return repaired[task.task_id]

    def _maybe_batch_self_repair(
        self,
        candidates: List[tuple["ExecutionTask", TaskExecutionOutcome]],
        *,
        batch_results: List[ExecutionResult],
        run_id: str,
        tenant_id: str,
        mode: ExecutionMode,
    ) -> Dict[str, tuple[TaskExecutionOutcome, str]]:
        """Attempt at most one bounded coder repair pass over *candidates* (E41-S5, E46-S3).

        Only called with "validation" tasks whose ``commands`` came from
        agent structured output (E41-S4) — a keyword-sniffed command never
        reaches this method, so stub/unconfigured-provider runs are
        unaffected. Every *candidate* that already passed short-circuits to
        ``"first_try_pass"`` without touching the Coder.

        Gated on failure classification (E46-S2, ADR-023): a candidate
        whose failed results are all classified and none is
        :attr:`~backend.execution.contracts.ExecutionResult.repairable_by_code_change`
        (e.g. a sandbox policy rejection, a disallowed command, an
        unavailable environment) is reported ``"skipped_non_repairable"``
        without joining the repair pass at all — no Coder call, no
        re-execution. A result with no ``failure_kind`` (produced before
        E46-S1, or by a producer not yet updated to classify) fails that
        candidate's gate open to the pre-E46-S2 reflex.

        Batched repair (E46-S3): every remaining, repairable candidate is
        combined into **one** Coder call carrying every candidate's
        failure evidence and every file the batch wrote (never a fresh
        full plan) — not one call per failed task. The repaired files are
        applied as a single write (still gated through
        :meth:`_resolve_task_actions`, the same approval-mode gate as any
        other write; a pending decision there is treated as a failed
        repair rather than a second nested pause). Only the candidates
        that were actually repaired are re-validated afterwards, each with
        its own command — a task that passed on the first try, or whose
        failure was skipped as non-repairable, is never re-run.

        Args:
            candidates: ``(task, validation_outcome)`` pairs for every
                "validation" task in the batch with agent-declared
                ``commands`` — the only tasks eligible for self-repair.
            batch_results: The batch's running list of every dispatched
                result; read for ``written_paths`` and mutated in place
                with any repair-write/revalidation results this pass
                produces, so the caller's artifact collection sees them.

        Returns:
            A mapping of ``task_id`` -> ``(outcome, self_check)`` covering
            every candidate — ``outcome`` is the candidate's original
            outcome when no repair was attempted; ``self_check`` is one of
            ``"first_try_pass"``, ``"repaired_then_pass"``,
            ``"failed_after_retry"``, or ``"skipped_non_repairable"``.
        """
        results: Dict[str, tuple[TaskExecutionOutcome, str]] = {}
        repairable: List[tuple["ExecutionTask", TaskExecutionOutcome, List[ExecutionResult]]] = []

        for task, validation_outcome in candidates:
            if validation_outcome.status == "completed":
                results[task.task_id] = (validation_outcome, "first_try_pass")
                continue

            failed_results = [result for result in validation_outcome.results if result.status == "failed"]
            has_unclassified_failure = any(result.failure_kind is None for result in failed_results)
            if failed_results and not has_unclassified_failure and not any(
                result.repairable_by_code_change for result in failed_results
            ):
                skip_kind = failed_results[0].failure_kind
                assert skip_kind is not None  # guaranteed by has_unclassified_failure above
                events.emit_event(
                    "execution.repair.skipped",
                    tenant_id=tenant_id,
                    partition_key=run_id,
                    data={
                        "taskId": task.task_id,
                        "failureKind": skip_kind.value,
                        "reason": (
                            f"failure kind {skip_kind.value!r} is not repairable by a code change"
                        ),
                    },
                    subject={"runId": run_id, "taskId": task.task_id},
                )
                results[task.task_id] = (validation_outcome, "skipped_non_repairable")
                continue

            repairable.append((task, validation_outcome, failed_results))

        if not repairable:
            return results

        written_paths = sorted({path for result in batch_results for path in result.artifacts})
        if not written_paths or self._project_root is None:
            for task, validation_outcome, _ in repairable:
                results[task.task_id] = (validation_outcome, "failed_after_retry")
            return results

        root = self._project_root.resolve()
        file_contents: Dict[str, str] = {}
        for rel_path in written_paths:
            try:
                file_contents[rel_path] = (root / rel_path).read_text(encoding="utf-8")
            except OSError:
                continue
        if not file_contents:
            for task, validation_outcome, _ in repairable:
                results[task.task_id] = (validation_outcome, "failed_after_retry")
            return results

        failure_lines: list[str] = []
        for task, _, failed_results in repairable:
            failure_lines.append(f"## {task.title} ({', '.join(task.commands)})")
            for result in failed_results:
                if result.stdout:
                    failure_lines.append(f"stdout:\n{result.stdout}")
                if result.stderr:
                    failure_lines.append(f"stderr:\n{result.stderr}")
                if result.error:
                    failure_lines.append(f"error: {result.error}")
        failure_output = "\n".join(failure_lines) or "validation command(s) failed"
        files_section = "\n\n".join(f"# {path}\n{content}" for path, content in file_contents.items())

        primary_task = repairable[0][0]
        repair_context = AgentContext(
            session_id=f"{run_id}-repair",
            goal=primary_task.description,
            user_request=(
                f"The following files were written but failed validation across "
                f"{len(repairable)} task(s). Fix them so every command passes.\n\n"
                f"Failure output:\n{failure_output}\n\n"
                f"Current file contents:\n{files_section}"
            ),
        )
        repair_result = self._require_agent("coder").run(repair_context)
        candidate_files = repair_result.metadata.get("files", [])
        repaired_files = [
            entry
            for entry in candidate_files
            if isinstance(entry, Mapping) and entry.get("path") in file_contents
        ]
        if not repaired_files:
            for task, validation_outcome, _ in repairable:
                results[task.task_id] = (validation_outcome, "failed_after_retry")
            return results

        write_actions = [
            ExecutionAction(
                action_id=f"{run_id}-batch-repair-write-{index}",
                type=ExecutionActionType.CREATE_FILE,
                task_id=primary_task.task_id,
                step_key=primary_task.task_id,
                path=entry["path"],
                content=entry["content"],
            )
            for index, entry in enumerate(repaired_files, start=1)
        ]
        write_outcome, write_pending = self._resolve_task_actions(
            task=primary_task, actions=write_actions, run_id=run_id, tenant_id=tenant_id, mode=mode
        )
        batch_results.extend(write_outcome.results if write_outcome is not None else [])
        if write_pending is not None or write_outcome is None or write_outcome.status != "completed":
            for task, validation_outcome, _ in repairable:
                combined = list(validation_outcome.results) + list(
                    write_outcome.results if write_outcome is not None else []
                )
                results[task.task_id] = (
                    TaskExecutionOutcome(status="failed", results=combined),
                    "failed_after_retry",
                )
            return results

        # Only the tasks that were actually repaired are re-run (E46-S3-T2)
        # -- a task that passed on the first try, or whose failure was
        # skipped as non-repairable, is never re-validated here.
        for task, validation_outcome, _ in repairable:
            revalidate_actions = self._task_executor.derive_actions(task)
            revalidate_outcome = self._task_executor.dispatch(
                revalidate_actions, run_id=run_id, tenant_id=tenant_id
            )
            batch_results.extend(revalidate_outcome.results)
            combined_results = (
                list(validation_outcome.results)
                + list(write_outcome.results)
                + list(revalidate_outcome.results)
            )
            self_check = (
                "repaired_then_pass" if revalidate_outcome.status == "completed" else "failed_after_retry"
            )
            results[task.task_id] = (
                TaskExecutionOutcome(status=revalidate_outcome.status, results=combined_results),
                self_check,
            )

        return results


__all__ = ["SelfRepairMixin"]
