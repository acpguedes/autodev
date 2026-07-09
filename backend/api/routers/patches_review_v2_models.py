"""Request/response schemas for the ``/v2/sessions/{session_id}/patches`` router (E16-S3).

Split out of ``patches_review_v2.py`` to keep that module under the
repository's 500-line-per-file limit. Pure data models — no request
handling logic lives here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.api.v2_common import SCHEMA_VERSION_V2, PageMetaV2

PatchStatus = str
"""One of ``"proposed"``, ``"applied"``, ``"discarded"`` (see the router's ``PatchStatus`` literal)."""


class PatchAuditEntryV2(BaseModel):
    """One audit trail entry attached to a patch record."""

    actor: str
    timestamp: str
    action: str
    result: str
    message: str = ""


class PatchProposeRequestV2(BaseModel):
    """Request body for ``POST /v2/sessions/{session_id}/patches``."""

    path: str = Field(..., min_length=1, description="Repository-relative path the patch targets.")
    original: str = Field(default="", description="Original file content.")
    updated: str = Field(default="", description="Proposed new file content.")


class PatchOverrideRequestV2(BaseModel):
    """Request body for the edited-content override endpoint."""

    updated: str = Field(..., description="Reviewer-edited replacement for the proposed content.")


class PatchApplyRequestV2(BaseModel):
    """Request body for the apply endpoint.

    ``apply`` defaults to ``False`` (dry-run): the engine computes what would
    happen but never writes to disk. Set ``apply=True`` to perform a real
    apply.
    """

    apply: bool = Field(default=False, description="Set true to perform a real, non-dry-run apply.")


class ChangedFileV2(BaseModel):
    """A single changed file entry, as returned by the changed-file list."""

    schemaVersion: str = SCHEMA_VERSION_V2
    patch_id: str
    path: str
    status: PatchStatus
    added_lines: int
    removed_lines: int


class ChangedFileListV2(BaseModel):
    """Paginated collection of :class:`ChangedFileV2`."""

    schemaVersion: str = SCHEMA_VERSION_V2
    session_id: str
    items: list[ChangedFileV2]
    page: PageMetaV2


class PatchDetailV2(BaseModel):
    """A single patch record, including its unified diff and audit trail."""

    schemaVersion: str = SCHEMA_VERSION_V2
    patch_id: str
    session_id: str
    path: str
    status: PatchStatus
    original: str
    updated: str
    diff: str
    added_lines: int
    removed_lines: int
    audit: list[PatchAuditEntryV2]


class PatchApplyResultV2(BaseModel):
    """Result of an apply attempt (dry-run or real)."""

    schemaVersion: str = SCHEMA_VERSION_V2
    patch_id: str
    session_id: str
    path: str
    applied: bool
    dry_run: bool
    message: str
    audit: PatchAuditEntryV2


__all__ = [
    "ChangedFileListV2",
    "ChangedFileV2",
    "PatchApplyRequestV2",
    "PatchApplyResultV2",
    "PatchAuditEntryV2",
    "PatchDetailV2",
    "PatchOverrideRequestV2",
    "PatchProposeRequestV2",
    "PatchStatus",
]
