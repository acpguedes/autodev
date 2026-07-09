"""v2 Control Plane API — patch review and apply lifecycle (E16-S3).

Exposes a session-scoped patch review queue on top of the existing E0 patch
engine (:mod:`backend.patches.engine`): a client proposes a candidate patch,
lists the session's changed files with +/- stats, retrieves a unified diff
per file, optionally submits an edited-content override, and finally applies
(dry-run by default) or discards it. This is new surface — the legacy
``POST /patches/generate`` (``backend/api/routers/patches.py``,
``frontend/lib/api_ext.ts::generatePatch``) only diffs two inline strings
and never enumerates a run's changed files nor persists a reviewable queue.

Design notes:

* **Storage.** Per ``docs/v2_platform/phases/e16_redesign_api_enablement.md``
  §E16-S3, this story's only declared dependencies are E9-S1 (Control Plane
  API core) and E0 (the patch engine) — it intentionally does not depend on
  E3 (the orchestration/plan store), unlike E16-S2. There is therefore no
  durable "run produced these files" data source to read from yet: the
  review queue is populated by the propose endpoint below and held in an
  in-process registry (module-level dict), mirroring the placeholder-seam
  convention already used by ``backend/api/rbac_v2.py`` until a durable
  store is warranted by a future story.
* **Concurrency.** ``_STORE_LOCK`` guards every read and write of
  :data:`_PATCH_STORE` and of an individual :class:`_PatchRecord`'s mutable
  fields (``status``, ``updated``, ``diff``, ``audit_log``). FastAPI runs
  synchronous route handlers in a thread pool, so two concurrent requests
  against the same ``patch_id`` (e.g. a client retry) are a realistic race;
  each handler holds the lock for its whole check-then-act sequence —
  including the call into the engine for apply — so a patch can only ever
  transition out of ``proposed`` once.
* **Engine reuse.** Every diff computation goes through
  :func:`backend.patches.engine.generate_patch` and every filesystem write
  goes through :func:`backend.patches.engine.apply_patch` — this module
  never writes to disk directly, so the engine's path-traversal guard is the
  single source of truth for "does an apply stay inside the guarded root".
* **Audit.** Every apply/discard call appends a :class:`PatchAuditEntryV2`
  (actor, timestamp, action, result) to the patch record, satisfying the
  story's auditability requirement without introducing a new logging
  subsystem.

Request/response schemas live in the sibling module
``patches_review_v2_models`` to keep this file under the repository's
500-line-per-file limit.

This router is auto-included by
``backend.api.routers.include_all_routers()`` — no changes to ``main.py``
are required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends

from backend.api.rbac_v2 import PrincipalV2, require_v2_principal
from backend.api.routers.patches_review_v2_models import (
    ChangedFileListV2,
    ChangedFileV2,
    PatchApplyRequestV2,
    PatchApplyResultV2,
    PatchAuditEntryV2,
    PatchDetailV2,
    PatchOverrideRequestV2,
    PatchProposeRequestV2,
)
from backend.api.v2_common import PaginationParams, paginate, v2_error
from backend.config.runtime import get_runtime_config_service
from backend.events.catalog import PatchAppliedData
from backend.events.runtime import emit_event
from backend.patches.engine import apply_patch, generate_patch
from backend.patches.models import Patch

router = APIRouter(prefix="/v2/sessions/{session_id}/patches", tags=["patches"], dependencies=[Depends(require_v2_principal)])

_DEFAULT_TENANT_ID = "default"

PatchStatus = Literal["proposed", "applied", "discarded"]


# ---------------------------------------------------------------------------
# In-process review store
# ---------------------------------------------------------------------------


@dataclass
class _AuditEntry:
    """One audit trail entry for a patch record."""

    actor: str
    timestamp: str
    action: str
    result: str
    message: str = ""


@dataclass
class _PatchRecord:
    """A proposed patch under review, scoped to a session.

    ``added_lines``/``removed_lines`` are computed once, whenever ``diff``
    is (re)written (on propose and on override), rather than being
    recomputed from ``diff`` on every read.
    """

    patch_id: str
    session_id: str
    path: str
    original: str
    updated: str
    diff: str
    added_lines: int
    removed_lines: int
    status: PatchStatus = "proposed"
    audit_log: list[_AuditEntry] = field(default_factory=list)


_STORE_LOCK = threading.Lock()
_PATCH_STORE: dict[str, dict[str, _PatchRecord]] = {}


def reset_patch_review_store_for_tests() -> None:
    """Clear the in-process patch review registry — for use in test fixtures."""
    with _STORE_LOCK:
        _PATCH_STORE.clear()


def _diff_stats(diff: str) -> tuple[int, int]:
    """Count added/removed content lines in a unified diff.

    Mirrors the counting rule already used by the ``summarize_diff`` builtin
    skill (``backend/skills/builtin/summarize_diff.py``): lines starting with
    ``+``/``-`` are counted, excluding the ``+++``/``---`` file-header lines.

    Args:
        diff: Unified diff text.

    Returns:
        Tuple of ``(added_lines, removed_lines)``.
    """
    added = 0
    removed = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _get_patch_or_404_locked(session_id: str, patch_id: str) -> _PatchRecord:
    """Fetch a patch record while holding ``_STORE_LOCK``, raising a v2 404 when missing.

    Callers must invoke this only from within a ``with _STORE_LOCK:`` block.
    """
    session_patches = _PATCH_STORE.get(session_id, {})
    record = session_patches.get(patch_id)
    if record is None:
        v2_error(404, f"Unknown patch_id {patch_id!r} for session {session_id!r}.")
    return record


def get_patch_workspace_root() -> Path:
    """Resolve the filesystem root patches are applied against (or rejected outside of).

    Constructed fresh per request from the shared runtime configuration,
    matching the convention used by every other ``/v2`` router's service
    provider. Overridable via ``app.dependency_overrides`` in tests so real
    applies never touch the actual repository working tree.

    Returns:
        The configured project root.
    """
    config_service = get_runtime_config_service()
    runtime_config = config_service.apply_to_environment()
    return Path(runtime_config.repository.project_root)


def _to_changed_file_v2(record: _PatchRecord) -> ChangedFileV2:
    """Convert a :class:`_PatchRecord` into its changed-file list-item response model."""
    return ChangedFileV2(
        patch_id=record.patch_id,
        path=record.path,
        status=record.status,
        added_lines=record.added_lines,
        removed_lines=record.removed_lines,
    )


def _to_patch_detail_v2(record: _PatchRecord) -> PatchDetailV2:
    """Convert a :class:`_PatchRecord` into its detail response model."""
    return PatchDetailV2(
        patch_id=record.patch_id,
        session_id=record.session_id,
        path=record.path,
        status=record.status,
        original=record.original,
        updated=record.updated,
        diff=record.diff,
        added_lines=record.added_lines,
        removed_lines=record.removed_lines,
        audit=[
            PatchAuditEntryV2(actor=entry.actor, timestamp=entry.timestamp, action=entry.action, result=entry.result, message=entry.message)
            for entry in record.audit_log
        ],
    )


def _now() -> str:
    """Return the current UTC timestamp in ISO 8601 form."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=PatchDetailV2, status_code=201)
def propose_patch_v2(
    session_id: str,
    request: PatchProposeRequestV2,
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> PatchDetailV2:
    """Propose a candidate patch for review under a session.

    Computes the unified diff via the E0 patch engine's
    :func:`~backend.patches.engine.generate_patch` and stores it in the
    session's review queue with status ``proposed``.

    Args:
        session_id: Identifier of the session the patch belongs to.
        request: Path plus original/updated content to diff.
        principal: Authenticated caller (recorded on the initial audit entry).

    Returns:
        The newly proposed patch, including its computed diff.
    """
    patch = generate_patch(request.path, request.original, request.updated)
    added, removed = _diff_stats(patch.diff)
    patch_id = f"patch_{uuid4().hex}"
    record = _PatchRecord(
        patch_id=patch_id,
        session_id=session_id,
        path=patch.path,
        original=patch.original,
        updated=patch.updated,
        diff=patch.diff,
        added_lines=added,
        removed_lines=removed,
        audit_log=[_AuditEntry(actor=principal.subject, timestamp=_now(), action="propose", result="proposed")],
    )
    with _STORE_LOCK:
        _PATCH_STORE.setdefault(session_id, {})[patch_id] = record
        return _to_patch_detail_v2(record)


@router.get("", response_model=ChangedFileListV2)
def list_changed_files_v2(
    session_id: str,
    pagination: PaginationParams = Depends(),
) -> ChangedFileListV2:
    """List a session's changed files with +/- line stats.

    Emits ``patch.changedfiles.listed`` on the E9-S3 event bus.

    Args:
        session_id: Identifier of the session (or run) whose changed files
            are being reviewed.
        pagination: Shared limit/offset pagination window.

    Returns:
        A paginated collection of changed-file summaries.
    """
    with _STORE_LOCK:
        records = list(_PATCH_STORE.get(session_id, {}).values())
        items = [_to_changed_file_v2(record) for record in records]
    page, page_meta = paginate(items, pagination)
    emit_event(
        "patch.changedfiles.listed",
        tenant_id=_DEFAULT_TENANT_ID,
        partition_key=session_id,
        data={"sessionId": session_id, "fileCount": len(items)},
        subject={"sessionId": session_id},
    )
    return ChangedFileListV2(session_id=session_id, items=page, page=page_meta)


@router.get("/{patch_id}", response_model=PatchDetailV2)
def get_patch_diff_v2(session_id: str, patch_id: str) -> PatchDetailV2:
    """Retrieve a single changed file's unified diff and current status.

    Args:
        session_id: Identifier of the session the patch belongs to.
        patch_id: Identifier of the patch to fetch.

    Returns:
        The patch detail, including its unified diff and audit trail.

    Raises:
        HTTPException: 404 if ``patch_id`` is unknown for ``session_id``.
    """
    with _STORE_LOCK:
        record = _get_patch_or_404_locked(session_id, patch_id)
        return _to_patch_detail_v2(record)


@router.put("/{patch_id}/content", response_model=PatchDetailV2)
def override_patch_content_v2(
    session_id: str,
    patch_id: str,
    request: PatchOverrideRequestV2,
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> PatchDetailV2:
    """Submit a reviewer-edited replacement for a proposed patch's content.

    Recomputes the unified diff against the patch's original content via the
    E0 patch engine. Only patches still in the ``proposed`` state may be
    overridden.

    Args:
        session_id: Identifier of the session the patch belongs to.
        patch_id: Identifier of the patch to override.
        request: The edited replacement content.
        principal: Authenticated caller (recorded on the audit entry).

    Returns:
        The patch detail after the override, with its recomputed diff.

    Raises:
        HTTPException: 404 if unknown; 409 if the patch is no longer
            ``proposed``.
    """
    with _STORE_LOCK:
        record = _get_patch_or_404_locked(session_id, patch_id)
        if record.status != "proposed":
            v2_error(409, f"Patch {patch_id!r} is {record.status!r}; only 'proposed' patches accept an override.")
        patch = generate_patch(record.path, record.original, request.updated)
        record.updated = patch.updated
        record.diff = patch.diff
        record.added_lines, record.removed_lines = _diff_stats(patch.diff)
        record.audit_log.append(_AuditEntry(actor=principal.subject, timestamp=_now(), action="override", result="content_overridden"))
        return _to_patch_detail_v2(record)


@router.post("/{patch_id}/apply", response_model=PatchApplyResultV2)
def apply_patch_v2(
    session_id: str,
    patch_id: str,
    request: PatchApplyRequestV2 = PatchApplyRequestV2(),
    principal: PrincipalV2 = Depends(require_v2_principal),
    workspace_root: Path = Depends(get_patch_workspace_root),
) -> PatchApplyResultV2:
    """Apply (or dry-run) a proposed patch through the E0 patch engine.

    Dry-run by default: pass ``{"apply": true}`` to perform a real,
    non-dry-run write. A real apply is rejected — without writing — if the
    patch's path resolves outside ``workspace_root`` (the engine's
    path-traversal guard); every attempt, successful or not, is recorded on
    the patch's audit trail. The whole check-then-act sequence, including
    the engine call, runs under ``_STORE_LOCK`` so a patch can transition out
    of ``proposed`` at most once even under concurrent requests.

    Args:
        session_id: Identifier of the session the patch belongs to.
        patch_id: Identifier of the patch to apply.
        request: Apply flags; ``apply=False`` (default) performs a dry-run.
        principal: Authenticated caller (recorded on the audit entry as the
            actor responsible for this apply).
        workspace_root: Guarded filesystem root a real apply must stay
            inside.

    Returns:
        The apply outcome, mirroring the engine's :class:`PatchResult`, plus
        the audit entry recorded for this attempt.

    Raises:
        HTTPException: 404 if unknown; 409 if the patch is no longer
            ``proposed``; 400 if the patch's path escapes ``workspace_root``.
    """
    with _STORE_LOCK:
        record = _get_patch_or_404_locked(session_id, patch_id)
        if record.status != "proposed":
            v2_error(409, f"Patch {patch_id!r} is {record.status!r}; only 'proposed' patches can be applied.")

        engine_patch = Patch(path=record.path, original=record.original, updated=record.updated, diff=record.diff)
        try:
            result = apply_patch(engine_patch, root=str(workspace_root), enable=request.apply)
        except ValueError as exc:
            entry = _AuditEntry(actor=principal.subject, timestamp=_now(), action="apply", result="denied", message=str(exc))
            record.audit_log.append(entry)
            v2_error(400, str(exc))

        outcome = "applied" if result.applied else "dry_run"
        entry = _AuditEntry(actor=principal.subject, timestamp=_now(), action="apply", result=outcome, message=result.message)
        record.audit_log.append(entry)

        if result.applied:
            record.status = "applied"
            added, removed = record.added_lines, record.removed_lines

        response = PatchApplyResultV2(
            patch_id=record.patch_id,
            session_id=session_id,
            path=record.path,
            applied=result.applied,
            dry_run=result.dry_run,
            message=result.message,
            audit=PatchAuditEntryV2(actor=entry.actor, timestamp=entry.timestamp, action=entry.action, result=entry.result, message=entry.message),
        )

    if result.applied:
        emit_event(
            "patch.applied",
            tenant_id=_DEFAULT_TENANT_ID,
            partition_key=session_id,
            data=PatchAppliedData(files=[record.path], additions=added, deletions=removed).model_dump(),
            subject={"sessionId": session_id, "patchId": patch_id},
        )

    return response


@router.post("/{patch_id}/discard", response_model=PatchDetailV2)
def discard_patch_v2(
    session_id: str,
    patch_id: str,
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> PatchDetailV2:
    """Discard a proposed patch without applying it.

    Emits ``patch.discarded`` on the E9-S3 event bus.

    Args:
        session_id: Identifier of the session the patch belongs to.
        patch_id: Identifier of the patch to discard.
        principal: Authenticated caller (recorded on the audit entry).

    Returns:
        The patch detail after being marked ``discarded``.

    Raises:
        HTTPException: 404 if unknown; 409 if the patch is no longer
            ``proposed``.
    """
    with _STORE_LOCK:
        record = _get_patch_or_404_locked(session_id, patch_id)
        if record.status != "proposed":
            v2_error(409, f"Patch {patch_id!r} is {record.status!r}; only 'proposed' patches can be discarded.")
        record.status = "discarded"
        record.audit_log.append(_AuditEntry(actor=principal.subject, timestamp=_now(), action="discard", result="discarded"))
        response = _to_patch_detail_v2(record)

    emit_event(
        "patch.discarded",
        tenant_id=_DEFAULT_TENANT_ID,
        partition_key=session_id,
        data={"sessionId": session_id, "patchId": patch_id, "path": record.path},
        subject={"sessionId": session_id, "patchId": patch_id},
    )
    return response


__all__ = [
    "apply_patch_v2",
    "discard_patch_v2",
    "get_patch_diff_v2",
    "get_patch_workspace_root",
    "list_changed_files_v2",
    "override_patch_content_v2",
    "propose_patch_v2",
    "reset_patch_review_store_for_tests",
    "router",
]
