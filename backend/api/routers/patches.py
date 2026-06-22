"""Patches API router — U13.

Exposes the merged ``backend.patches`` engine via two endpoints:

    POST /patches/generate  — body {path, original, updated}
                              returns the Patch incl. unified diff.
    POST /patches/apply     — body the Patch fields
                              honors env AUTODEV_ENABLE_PATCH_APPLY;
                              dry-run by default (applied=false, dry_run=true).

``backend.patches`` is lazily imported — returns 503 when absent so the
baseline suite is unaffected.

This router is auto-included by ``backend.api.routers.include_all_routers()``
— no changes to ``main.py`` are required.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["patches"])


# ---------------------------------------------------------------------------
# Lazy loader
# ---------------------------------------------------------------------------


def _get_patches():
    try:
        from backend.patches import apply_patch, generate_patch  # noqa: PLC0415
        return generate_patch, apply_patch
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="patches subsystem unavailable"
        ) from exc


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    path: str
    original: str
    updated: str


class PatchResponse(BaseModel):
    path: str
    original: str
    updated: str
    diff: str


class ApplyRequest(BaseModel):
    path: str
    original: str
    updated: str
    diff: str = ""


class PatchResultResponse(BaseModel):
    path: str
    applied: bool
    dry_run: bool
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/patches/generate", response_model=PatchResponse)
def generate_patch_endpoint(body: GenerateRequest) -> PatchResponse:
    """Generate a unified diff between *original* and *updated* for *path*."""
    generate_patch, _ = _get_patches()
    patch = generate_patch(body.path, body.original, body.updated)
    return PatchResponse(
        path=patch.path,
        original=patch.original,
        updated=patch.updated,
        diff=patch.diff,
    )


@router.post("/patches/apply", response_model=PatchResultResponse)
def apply_patch_endpoint(body: ApplyRequest) -> PatchResultResponse:
    """Apply a patch, honoring AUTODEV_ENABLE_PATCH_APPLY env flag.

    Dry-run by default (flag unset) — returns applied=false, dry_run=true.
    """
    _, apply_patch = _get_patches()
    try:
        from backend.patches.models import Patch  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="patches subsystem unavailable") from exc

    patch = Patch(
        path=body.path,
        original=body.original,
        updated=body.updated,
        diff=body.diff,
    )
    result = apply_patch(patch)
    return PatchResultResponse(
        path=result.path,
        applied=result.applied,
        dry_run=result.dry_run,
        message=result.message,
    )
