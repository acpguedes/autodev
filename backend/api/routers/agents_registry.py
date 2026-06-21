"""Agents registry API router — U6.

Exposes a read-only view of ALL known agents (defaults + registry-discovered):

* ``GET /agents``        — list all agents with name and metadata availability.
* ``GET /agents/{name}`` — describe one agent; 404 if unknown.

NOTE on route ordering: This router is auto-included by
``backend.api.routers.include_all_routers()`` BEFORE the inline
``@app.get("/agents/contracts")`` handler in ``main.py``.  To prevent the
``/agents/{name}`` wildcard from swallowing that path, the router exposes its
own ``GET /agents/contracts`` shim that calls the same underlying service.
This shim is placed first so FastAPI matches it before the wildcard.

This router is DISTINCT from the existing ``/agents/contracts`` endpoint in
that it ALSO registers ``/agents`` and ``/agents/{name}``.

Default agents (always present — defined in ``backend.agents``):
    planner, navigator, analyzer, architect, coder, devops, validator, responder

Registry-discovered agents (registered via ``@register_agent``):
    security, refactor, docs  (from ``backend.agents.{security,refactor,docs}``)

The ``metadata_model`` property of each agent instance is inspected to determine
whether a JSON schema is available for its structured output.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agents"])

# ---------------------------------------------------------------------------
# The 8 default agents — always listed even if instantiation is unavailable.
# ---------------------------------------------------------------------------

_DEFAULT_AGENT_NAMES: list[str] = [
    "planner",
    "navigator",
    "analyzer",
    "architect",
    "coder",
    "devops",
    "validator",
    "responder",
]


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AgentSummary(BaseModel):
    name: str
    has_metadata_contract: bool
    source: str  # "default" | "registry"


class AgentDetail(BaseModel):
    name: str
    has_metadata_contract: bool
    source: str
    metadata_schema: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Pass-through shim for /agents/contracts
#
# This route must be declared BEFORE /agents/{name} so that FastAPI matches
# the specific literal path first.  We call the orchestrator's
# describe_agent_contracts() directly; the response model matches
# AgentContractsResponse from main.py so the schema stays identical.
# ---------------------------------------------------------------------------


def _get_orchestrator_lazy() -> Any:
    """Lazily load the orchestrator dependency to avoid circular imports."""
    try:
        from backend.api.main import get_orchestrator  # noqa: PLC0415
        return get_orchestrator()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="orchestrator unavailable"
        ) from exc


@router.get("/agents/contracts", include_in_schema=False)
def agents_contracts_shim() -> Any:
    """Shim that delegates to the orchestrator's contract listing.

    Registered before ``/agents/{name}`` so the wildcard cannot steal this
    specific path.  The real ``@app.get("/agents/contracts")`` in main.py
    still exists and this keeps the routing consistent without editing main.py.
    """
    orchestrator = _get_orchestrator_lazy()
    contracts = orchestrator.describe_agent_contracts()
    return {"contracts": contracts}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_agent_map() -> Dict[str, Dict[str, Any]]:
    """Return a dict of name → {instance_or_None, source, has_contract}.

    Combines the 8 default agents (from ``backend.agents``) with any
    additional agents discovered from the registry.  Errors during import or
    instantiation are caught and logged; those agents appear with
    ``has_metadata_contract=False``.
    """
    result: Dict[str, Dict[str, Any]] = {}

    # 1. Default agents — try to import and instantiate each class.
    try:
        from backend.agents.contracts import AGENT_METADATA_MODELS  # noqa: PLC0415
    except ImportError:
        AGENT_METADATA_MODELS = {}

    _default_classes = {
        "planner": "backend.agents.planner.PlannerAgent",
        "navigator": "backend.agents.navigator.NavigatorAgent",
        "analyzer": "backend.agents.analyzer.AnalyzerAgent",
        "architect": "backend.agents.architect.ArchitectAgent",
        "coder": "backend.agents.coder.CoderAgent",
        "devops": "backend.agents.devops.DevOpsAgent",
        "validator": "backend.agents.validator.ValidatorAgent",
        "responder": "backend.agents.responder.ResponderAgent",
    }

    for name in _DEFAULT_AGENT_NAMES:
        import_path = _default_classes.get(name, "")
        instance = None
        if import_path:
            module_path, _, cls_name = import_path.rpartition(".")
            try:
                import importlib  # noqa: PLC0415
                mod = importlib.import_module(module_path)
                cls = getattr(mod, cls_name)
                # Some agents require project_root; try without first.
                try:
                    instance = cls()
                except TypeError:
                    instance = None
            except Exception:
                logger.debug("Could not instantiate default agent %r", name)

        has_contract = name in AGENT_METADATA_MODELS
        if instance is not None:
            try:
                model = instance.metadata_model()
                has_contract = model is not None
            except Exception:
                pass

        result[name] = {"instance": instance, "source": "default", "has_contract": has_contract}

    # 2. Registry-discovered agents (security, refactor, docs, …).
    # Import them explicitly so their module-level self-registration fires.
    _SPECIALIZED_IMPORTS = [
        "backend.agents.security",
        "backend.agents.refactor",
        "backend.agents.docs",
    ]
    for _mod_path in _SPECIALIZED_IMPORTS:
        try:
            import importlib as _il  # noqa: PLC0415
            _il.import_module(_mod_path)
        except Exception:
            logger.debug("Could not import specialized agent module %r", _mod_path)

    try:
        from backend.agents.registry import discover_agents  # noqa: PLC0415
        discovered = discover_agents()
        for name, instance in discovered.items():
            has_contract = False
            try:
                model = instance.metadata_model()
                has_contract = model is not None
            except Exception:
                pass
            # Don't overwrite defaults if a default registered itself.
            result.setdefault(
                name,
                {"instance": instance, "source": "registry", "has_contract": has_contract},
            )
            # But do update source/has_contract for registry-sourced entries.
            if name not in _DEFAULT_AGENT_NAMES:
                result[name] = {
                    "instance": instance,
                    "source": "registry",
                    "has_contract": has_contract,
                }
    except Exception:
        logger.debug("Could not discover registry agents", exc_info=True)

    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/agents", response_model=List[AgentSummary])
def list_agents() -> List[AgentSummary]:
    """Return all known agents (defaults + registry-discovered)."""
    agent_map = _build_agent_map()
    return [
        AgentSummary(
            name=name,
            has_metadata_contract=info["has_contract"],
            source=info["source"],
        )
        for name, info in sorted(agent_map.items())
    ]


@router.get("/agents/{name}", response_model=AgentDetail)
def describe_agent(name: str) -> AgentDetail:
    """Return details for one agent; 404 if the name is unknown."""
    agent_map = _build_agent_map()
    if name not in agent_map:
        raise HTTPException(status_code=404, detail=f"Agent {name!r} not found.")

    info = agent_map[name]
    schema: Optional[Dict[str, Any]] = None
    instance = info.get("instance")
    if instance is not None:
        try:
            model = instance.metadata_model()
            if model is not None:
                schema = model.model_json_schema()
        except Exception:
            pass

    # Fall back to AGENT_METADATA_MODELS if no instance available.
    if schema is None and info["has_contract"]:
        try:
            from backend.agents.contracts import AGENT_METADATA_MODELS  # noqa: PLC0415
            model_cls = AGENT_METADATA_MODELS.get(name)
            if model_cls is not None:
                schema = model_cls.model_json_schema()
        except Exception:
            pass

    return AgentDetail(
        name=name,
        has_metadata_contract=info["has_contract"],
        source=info["source"],
        metadata_schema=schema,
    )
