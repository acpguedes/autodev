"""v2 Skill Registry catalog API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.skills.registry_v2 import SkillRegistry

router = APIRouter(prefix="/v2/skills", tags=["skills"])


def get_skill_registry() -> SkillRegistry:
    """Build the skill registry dependency for request handlers.

    Returns:
        A new :class:`SkillRegistry` bound to the default durable store.
    """
    return SkillRegistry()


@router.get("")
def list_skill_catalog(registry: SkillRegistry = Depends(get_skill_registry)) -> dict[str, Any]:
    """List the full skill catalog.

    Args:
        registry: Skill registry dependency.

    Returns:
        The catalog document as a JSON-serializable dict.
    """
    registry.sync_from_plugin_store()
    return registry.catalog()


@router.get("/search")
def search_skills(
    trigger: str = Query(...),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> dict[str, Any]:
    """Search the skill catalog by trigger.

    Args:
        trigger: Trigger identifier to search for.
        registry: Skill registry dependency.

    Returns:
        The catalog document restricted to skills declaring ``trigger``.
    """
    registry.sync_from_plugin_store()
    return registry.catalog(trigger=trigger)


@router.get("/{skill_id:path}")
def get_skill(
    skill_id: str,
    version: str = Query(default="*"),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> dict[str, Any]:
    """Resolve a single skill by id and version range.

    Args:
        skill_id: Fully qualified skill id (``namespace/name``).
        version: SemVer range expression, or ``"*"`` for any version.
        registry: Skill registry dependency.

    Returns:
        The resolved skill's catalog item.

    Raises:
        HTTPException: 404 if no registered version satisfies ``version``.
    """
    registry.sync_from_plugin_store()
    try:
        ref = registry.resolve(skill_id, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ref.to_catalog_item()


__all__ = ["get_skill_registry", "router"]
