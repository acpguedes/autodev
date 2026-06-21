"""Job queue API router.

Exposes:
- ``POST /jobs`` — enqueue a job, return ``{job_id}``.
- ``GET  /jobs/{job_id}`` — return status and result.

Auto-included by ``backend.api.routers.include_all_routers`` via the standard
``router`` attribute — no changes to ``main.py`` required.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.jobs.queue import get_queue

router = APIRouter(tags=["jobs"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class EnqueueRequest(BaseModel):
    job_type: str
    payload: dict = {}


class EnqueueResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    result: object = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/jobs", response_model=EnqueueResponse, status_code=202)
def enqueue_job(request: EnqueueRequest) -> EnqueueResponse:
    """Submit a new job and return its ``job_id``."""
    queue = get_queue()
    job_id = queue.enqueue(request.job_type, request.payload)
    return EnqueueResponse(job_id=job_id)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Return the current status (and result) of *job_id*."""
    queue = get_queue()
    record = queue.get(job_id)
    if record["status"] == "error" and record.get("error", "").startswith("Unknown job_id"):
        raise HTTPException(status_code=404, detail=record["error"])
    return JobStatusResponse(**record)


__all__ = ["router"]
