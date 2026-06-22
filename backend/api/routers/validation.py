"""Validation API router — U15.

Surfaces the merged ``backend.validation`` sandbox runner over HTTP:

* ``POST /validation/run`` — body ``{command: [...], cwd?}``. Runs the command
  through :class:`backend.validation.SandboxRunner`, which is DISABLED by
  default (returns ``skipped=true, backend="disabled"``) unless the environment
  variable ``AUTODEV_ENABLE_SANDBOX`` is set.
* ``GET /validation/{job_id}`` — return the stored result for a prior run.

``backend.validation`` is imported lazily so an ``ImportError`` yields HTTP 503
rather than a startup crash. The router is auto-included by
``backend.api.routers.include_all_routers()`` — no changes to ``main.py``.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["validation"])

# Small in-process store so results are retrievable by job_id.
_RESULTS: Dict[str, Dict[str, Any]] = {}


def _import_validation():  # type: ignore[return]
    try:
        import backend.validation as _validation  # noqa: PLC0415

        return _validation
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="validation subsystem unavailable") from exc


class RunRequest(BaseModel):
    command: List[str]
    cwd: str = "."


class ValidationResultResponse(BaseModel):
    job_id: str
    returncode: int
    stdout: str
    stderr: str
    backend: str
    skipped: bool


@router.post("/validation/run", response_model=ValidationResultResponse)
def run_validation(body: RunRequest) -> ValidationResultResponse:
    """Run a validation command (no-op/skipped unless the sandbox is enabled)."""
    validation = _import_validation()
    if not body.command:
        raise HTTPException(status_code=400, detail="command must be a non-empty list")

    job_id = str(uuid.uuid4())
    job = validation.ValidationJob(job_id=job_id, command=body.command, cwd=body.cwd)
    result = validation.SandboxRunner().run(job)
    payload = {
        "job_id": result.job_id,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "backend": result.backend,
        "skipped": result.skipped,
    }
    _RESULTS[job_id] = payload
    return ValidationResultResponse(**payload)


@router.get("/validation/{job_id}", response_model=ValidationResultResponse)
def get_validation(job_id: str) -> ValidationResultResponse:
    """Return the stored result of a prior validation run; 404 if unknown."""
    _import_validation()
    if job_id not in _RESULTS:
        raise HTTPException(status_code=404, detail=f"validation job {job_id!r} not found")
    return ValidationResultResponse(**_RESULTS[job_id])
