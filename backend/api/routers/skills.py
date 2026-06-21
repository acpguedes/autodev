"""Skills API router — U3.

Exposes the skills subsystem via HTTP endpoints:

* ``GET  /skills``           — list all discovered skills (name + description).
* ``GET  /skills/{name}``    — describe a single skill; 404 if unknown.
* ``POST /skills/{name}/invoke`` — invoke a skill with ``{"inputs": {...}}``;
  returns :class:`SkillResult` fields as JSON.

The ``backend.skills`` package is imported lazily inside each handler so that
an ``ImportError`` (e.g. missing optional dependency) results in an HTTP 503
rather than a startup crash.

The router is auto-included by ``backend.api.routers.include_all_routers()``
— no changes to ``main.py`` are required.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["skills"])

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class SkillSummary(BaseModel):
    name: str
    description: str


class SkillDetail(BaseModel):
    name: str
    description: str


class InvokeRequest(BaseModel):
    inputs: Dict[str, Any] = {}


class InvokeResponse(BaseModel):
    content: str
    data: Dict[str, Any] = {}
    success: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_skills():  # type: ignore[return]
    """Lazy import of the skills subsystem; raises HTTP 503 on ImportError."""
    try:
        import backend.skills as _skills  # noqa: PLC0415
        return _skills
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="skills subsystem unavailable") from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/skills", response_model=List[SkillSummary])
def list_skills() -> List[SkillSummary]:
    """Return all registered skills with their names and descriptions."""
    skills_mod = _import_skills()
    registry = skills_mod.discover_skills()
    return [
        SkillSummary(
            name=name,
            description=getattr(instance, "description", "") or "",
        )
        for name, instance in sorted(registry.items())
    ]


@router.get("/skills/{name}", response_model=SkillDetail)
def describe_skill(name: str) -> SkillDetail:
    """Return details for a single skill; 404 if the name is unknown."""
    skills_mod = _import_skills()
    registry = skills_mod.discover_skills()
    if name not in registry:
        raise HTTPException(status_code=404, detail=f"Skill {name!r} not found.")
    instance = registry[name]
    return SkillDetail(
        name=name,
        description=getattr(instance, "description", "") or "",
    )


@router.post("/skills/{name}/invoke", response_model=InvokeResponse)
def invoke_skill(name: str, body: InvokeRequest) -> InvokeResponse:
    """Invoke a skill by name with the supplied inputs; 404 if unknown."""
    skills_mod = _import_skills()
    try:
        ctx = skills_mod.SkillContext(inputs=body.inputs)
        result = skills_mod.invoke_skill(name, ctx)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill {name!r} not found.")
    return InvokeResponse(content=result.content, data=result.data, success=result.success)
