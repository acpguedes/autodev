"""Skill registry and discovery.

Skills self-register via the :func:`register_skill` decorator.  Built-in
skills live in ``backend.skills.builtin``; importing that package causes them
to register themselves.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from backend.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_REGISTRY: Dict[str, Skill] = {}


def register_skill(name: str, description: str = ""):
    """Class/instance decorator that registers a skill under *name*.

    If given a *class*, it is instantiated (no arguments) and the instance is
    stored.  If given an already-instantiated object it is stored directly.
    The original class/object is returned unchanged so the decorator can be
    stacked or the class used normally.

    Duplicate names overwrite the previous entry with a warning.
    """

    def decorator(cls_or_instance: Any) -> Any:
        if isinstance(cls_or_instance, type):
            try:
                instance: Skill = cls_or_instance()
            except Exception:
                logger.exception(
                    "Failed to instantiate skill class %r for name %r — skipping registration",
                    cls_or_instance,
                    name,
                )
                return cls_or_instance
        else:
            instance = cls_or_instance

        if description and not getattr(instance, "description", None):
            # Attach description only if the instance has none of its own.
            try:
                object.__setattr__(instance, "description", description)
            except (AttributeError, TypeError):
                pass

        if name in _REGISTRY:
            logger.warning(
                "Skill name %r already registered; overwriting with %r",
                name,
                cls_or_instance,
            )
        _REGISTRY[name] = instance
        return cls_or_instance

    return decorator


def get_registry() -> Dict[str, Skill]:
    """Return the current registry dict (name → instance)."""
    return dict(_REGISTRY)


def discover_skills() -> Dict[str, Skill]:
    """Import built-in skills (triggering self-registration) and return the registry.

    Built-in skills in ``backend.skills.builtin`` register themselves on
    import.  Importing the package here ensures they are always present when
    the registry is consulted.
    """
    try:
        import backend.skills.builtin  # noqa: F401 — side-effect import
    except Exception:
        logger.exception("Failed to import backend.skills.builtin — built-ins may be missing")

    return get_registry()


def invoke_skill(name: str, context: SkillContext) -> SkillResult:
    """Invoke a registered skill by *name*.

    Raises :class:`KeyError` if the skill is not found.
    """
    registry = discover_skills()
    if name not in registry:
        raise KeyError(f"Unknown skill: {name!r}.  Available: {sorted(registry)}")
    return registry[name].run(context)


__all__ = [
    "register_skill",
    "get_registry",
    "discover_skills",
    "invoke_skill",
]
