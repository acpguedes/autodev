"""v2 Control Plane API — unified extension catalog (E16-S4).

Aggregates the existing agent (E9), skill (E9), plugin (E9), and MCP
allowlist (E9-S4) catalogs into a single, typed listing for the prototype's
extensions screen, and exposes enable/disable and agent create/edit actions
that delegate to each subsystem's own activation mechanism instead of
introducing a second source of truth or a parallel activation store:

* ``agent``/``skill`` enable-disable toggles the registry's own
  ``deprecated`` flag (:meth:`~backend.agents.registry_v2.AgentRegistry.activate`
  / :meth:`~backend.agents.registry_v2.AgentRegistry.deprecate` and their
  skill-registry counterparts).
* ``plugin`` enable-disable delegates to
  :class:`~backend.plugins.host.PluginHost`'s lifecycle state machine.
* ``mcp`` enable-disable mutates the ``AUTODEV_MCP_EXPOSED_SKILLS``
  allowlist env var backing
  :meth:`~backend.config.settings.Settings.mcp_exposed_skills`, preserving
  the E9-S4-T3 least-privilege mapping.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.agents.manifest import validate_agent_manifest
from backend.agents.registry_v2 import AgentRef, AgentRegistry
from backend.api.v2_common import PageMetaV2, PaginationParams, SCHEMA_VERSION_V2, paginate, v2_error
from backend.config.settings import Settings, get_settings, reset_settings_cache
from backend.plugins.host import PluginHost, PluginState
from backend.plugins.registry import ActivePluginRegistry
from backend.skills.registry_v2 import SkillRef, SkillRegistry

router = APIRouter(prefix="/v2/extensions", tags=["extensions"])

ExtensionKind = Literal["agent", "skill", "plugin", "mcp"]

# Synthetic plugin id attached to agents created directly through the API,
# which have no backing installed plugin.
CUSTOM_AGENT_PLUGIN_ID = "autodev/custom-agents"


class ExtensionItemV2(BaseModel):
    """A single entry in the unified extension catalog."""

    kind: str
    id: str
    name: str
    enabled: bool
    pluginId: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class ExtensionCatalogResponseV2(BaseModel):
    """Paginated, typed listing of every known extension."""

    schemaVersion: str = SCHEMA_VERSION_V2
    items: list[ExtensionItemV2]
    page: PageMetaV2


class ExtensionActionResponseV2(BaseModel):
    """Result of an enable/disable action on a single catalog entry."""

    schemaVersion: str = SCHEMA_VERSION_V2
    item: ExtensionItemV2


class AgentUpsertRequestV2(BaseModel):
    """Request body for creating or editing an agent extension."""

    version: str = "1.0.0"
    displayName: str | None = None
    description: str | None = None
    systemPrompt: str = ""
    model: str = "gpt-4o-mini"
    allowedTools: list[str] = Field(default_factory=list)


class AgentExtensionResponseV2(BaseModel):
    """Detail view of an agent extension, including its editable fields."""

    schemaVersion: str = SCHEMA_VERSION_V2
    item: ExtensionItemV2
    systemPrompt: str
    model: str
    allowedTools: list[str]


def get_agent_registry() -> AgentRegistry:
    """Build the agent registry dependency for request handlers.

    Returns:
        A new :class:`AgentRegistry` bound to the default durable store.
    """
    return AgentRegistry()


def get_skill_registry() -> SkillRegistry:
    """Build the skill registry dependency for request handlers.

    Returns:
        A new :class:`SkillRegistry` bound to the default durable store.
    """
    return SkillRegistry()


def get_active_plugin_registry() -> ActivePluginRegistry:
    """Build the active plugin registry dependency for request handlers.

    Returns:
        A new :class:`ActivePluginRegistry`.
    """
    return ActivePluginRegistry()


def get_plugin_host() -> PluginHost:
    """Build the plugin host dependency for request handlers.

    Returns:
        A new :class:`PluginHost` bound to the default durable store.
    """
    return PluginHost()


def _dedupe_latest(refs: list[Any], *, key: Any) -> list[Any]:
    """Keep only the first (highest-version) ref for each dedupe key.

    Args:
        refs: References sorted with the highest version first per id
            (the ordering produced by ``list_agents``/``list_skills``).
        key: Callable extracting the dedupe key from a ref.

    Returns:
        One ref per distinct key.
    """
    seen: set[Any] = set()
    deduped: list[Any] = []
    for ref in refs:
        ref_key = key(ref)
        if ref_key in seen:
            continue
        seen.add(ref_key)
        deduped.append(ref)
    return deduped


def _agent_item(ref: AgentRef) -> ExtensionItemV2:
    """Render an agent registration as a unified catalog item."""
    return ExtensionItemV2(
        kind="agent",
        id=ref.agent_id,
        name=ref.manifest.display_name or ref.agent_id,
        enabled=not ref.deprecated,
        pluginId=ref.plugin_id,
        detail={
            "version": ref.version,
            "capabilities": [capability.id for capability in ref.manifest.capabilities],
        },
    )


def _skill_item(ref: SkillRef) -> ExtensionItemV2:
    """Render a skill registration as a unified catalog item."""
    return ExtensionItemV2(
        kind="skill",
        id=ref.skill_id,
        name=ref.manifest.name or ref.skill_id,
        enabled=not ref.deprecated,
        pluginId=ref.plugin_id,
        detail={"version": ref.version, "triggers": list(ref.manifest.triggers)},
    )


def _plugin_item(entry: dict[str, Any]) -> ExtensionItemV2:
    """Render an active-plugin-registry snapshot entry as a unified catalog item."""
    return ExtensionItemV2(
        kind="plugin",
        id=entry["id"],
        name=entry["id"],
        enabled=True,
        pluginId=entry["id"],
        detail={"version": entry["version"], "extensionPoints": entry["extensionPoints"]},
    )


def _mcp_item(ref: SkillRef, exposed: set[str]) -> ExtensionItemV2:
    """Render a skill as its MCP-exposure catalog item.

    Args:
        ref: The skill the MCP entry mirrors.
        exposed: The current MCP allowlist (E9-S4-T3).
    """
    return ExtensionItemV2(
        kind="mcp",
        id=ref.skill_id,
        name=ref.manifest.name or ref.skill_id,
        enabled=ref.skill_id in exposed,
        pluginId=ref.plugin_id,
        detail={"version": ref.version},
    )


def _build_catalog(
    agent_registry: AgentRegistry,
    skill_registry: SkillRegistry,
    plugin_registry: ActivePluginRegistry,
    settings: Settings,
) -> list[ExtensionItemV2]:
    """Compose the unified extension catalog from each subsystem's own source of truth."""
    agent_registry.sync_from_plugin_store()
    skill_registry.sync_from_plugin_store()
    agent_refs = _dedupe_latest(agent_registry.list_agents(), key=lambda ref: ref.agent_id)
    skill_refs = _dedupe_latest(skill_registry.list_skills(), key=lambda ref: ref.skill_id)
    exposed = set(settings.mcp_exposed_skills())

    items = [_agent_item(ref) for ref in agent_refs]
    items += [_skill_item(ref) for ref in skill_refs]
    items += [_plugin_item(entry) for entry in plugin_registry.snapshot()["activePlugins"]]
    items += [_mcp_item(ref, exposed) for ref in skill_refs]
    return items


@router.get("", response_model=ExtensionCatalogResponseV2)
def list_extensions(
    kind: ExtensionKind | None = Query(default=None, description="Filter to a single extension kind."),
    pagination: PaginationParams = Depends(),
    agent_registry: AgentRegistry = Depends(get_agent_registry),
    skill_registry: SkillRegistry = Depends(get_skill_registry),
    plugin_registry: ActivePluginRegistry = Depends(get_active_plugin_registry),
) -> ExtensionCatalogResponseV2:
    """List the unified extension catalog (agents, skills, plugins, MCP servers).

    Args:
        kind: Optional filter restricting the listing to one extension kind.
        pagination: Shared ``limit``/``offset`` window.
        agent_registry: Agent registry dependency.
        skill_registry: Skill registry dependency.
        plugin_registry: Active plugin registry dependency.

    Returns:
        The paginated, typed catalog.
    """
    items = _build_catalog(agent_registry, skill_registry, plugin_registry, get_settings())
    if kind is not None:
        items = [item for item in items if item.kind == kind]
    page_items, meta = paginate(items, pagination)
    return ExtensionCatalogResponseV2(items=page_items, page=meta)


def _toggle_agent(registry: AgentRegistry, agent_id: str, enabled: bool) -> ExtensionItemV2:
    """Enable or disable an agent by toggling its registry ``deprecated`` flag."""
    try:
        ref = registry.resolve(agent_id, "*")
    except KeyError as exc:
        v2_error(404, str(exc))
    if enabled:
        registry.activate(ref.agent_id, ref.version)
    else:
        registry.deprecate(ref.agent_id, ref.version, "Disabled via /v2/extensions")
    return _agent_item(registry.resolve(agent_id, "*"))


def _toggle_skill(registry: SkillRegistry, skill_id: str, enabled: bool) -> ExtensionItemV2:
    """Enable or disable a skill by toggling its registry ``deprecated`` flag."""
    try:
        ref = registry.resolve(skill_id, "*")
    except KeyError as exc:
        v2_error(404, str(exc))
    if enabled:
        registry.activate(ref.skill_id, ref.version)
    else:
        registry.deprecate(ref.skill_id, ref.version, "Disabled via /v2/extensions")
    return _skill_item(registry.resolve(skill_id, "*"))


def _toggle_plugin(host: PluginHost, plugin_id: str, enabled: bool) -> ExtensionItemV2:
    """Enable or disable a plugin by delegating to :class:`PluginHost`'s lifecycle."""
    try:
        record = host.enable(plugin_id) if enabled else host.disable(plugin_id)
    except KeyError as exc:
        v2_error(404, f"Unknown plugin: {exc}")
    except ValueError as exc:
        v2_error(400, str(exc))
    return ExtensionItemV2(
        kind="plugin",
        id=record.plugin_id,
        name=record.plugin_id,
        enabled=record.state == PluginState.ENABLED,
        pluginId=record.plugin_id,
        detail={"version": record.version, "state": record.state.value},
    )


def _toggle_mcp(skill_registry: SkillRegistry, skill_id: str, enabled: bool) -> ExtensionItemV2:
    """Enable or disable a skill's MCP exposure by mutating the allowlist env var."""
    try:
        ref = skill_registry.resolve(skill_id, "*")
    except KeyError as exc:
        v2_error(404, str(exc))
    settings = get_settings()
    exposed = set(settings.mcp_exposed_skills())
    if enabled:
        exposed.add(skill_id)
    else:
        exposed.discard(skill_id)
    os.environ["AUTODEV_MCP_EXPOSED_SKILLS"] = ",".join(sorted(exposed))
    reset_settings_cache()
    return _mcp_item(ref, exposed)


def _dispatch_toggle(
    kind: str,
    item_id: str,
    enabled: bool,
    agent_registry: AgentRegistry,
    skill_registry: SkillRegistry,
    plugin_host: PluginHost,
) -> ExtensionItemV2:
    """Route an enable/disable action to the owning subsystem's activation mechanism."""
    if kind == "agent":
        return _toggle_agent(agent_registry, item_id, enabled)
    if kind == "skill":
        return _toggle_skill(skill_registry, item_id, enabled)
    if kind == "plugin":
        return _toggle_plugin(plugin_host, item_id, enabled)
    if kind == "mcp":
        return _toggle_mcp(skill_registry, item_id, enabled)
    v2_error(400, f"Unknown extension kind: {kind}")


def _toggle_response(
    kind: ExtensionKind,
    item_id: str,
    enabled: bool,
    agent_registry: AgentRegistry,
    skill_registry: SkillRegistry,
    plugin_host: PluginHost,
) -> ExtensionActionResponseV2:
    """Shared handler body for the enable/disable actions; see callers below."""
    item = _dispatch_toggle(kind, item_id, enabled, agent_registry, skill_registry, plugin_host)
    return ExtensionActionResponseV2(item=item)


@router.post("/{kind}/{item_id:path}/enable", response_model=ExtensionActionResponseV2)
def enable_extension(
    kind: ExtensionKind,
    item_id: str,
    agent_registry: AgentRegistry = Depends(get_agent_registry),
    skill_registry: SkillRegistry = Depends(get_skill_registry),
    plugin_host: PluginHost = Depends(get_plugin_host),
) -> ExtensionActionResponseV2:
    """Enable a catalog entry, delegating to its owning subsystem."""
    return _toggle_response(kind, item_id, True, agent_registry, skill_registry, plugin_host)


@router.post("/{kind}/{item_id:path}/disable", response_model=ExtensionActionResponseV2)
def disable_extension(
    kind: ExtensionKind,
    item_id: str,
    agent_registry: AgentRegistry = Depends(get_agent_registry),
    skill_registry: SkillRegistry = Depends(get_skill_registry),
    plugin_host: PluginHost = Depends(get_plugin_host),
) -> ExtensionActionResponseV2:
    """Disable a catalog entry, delegating to its owning subsystem."""
    return _toggle_response(kind, item_id, False, agent_registry, skill_registry, plugin_host)


def _build_raw_manifest(agent_id: str, payload: AgentUpsertRequestV2) -> dict[str, Any]:
    """Build a raw, camelCase agent manifest document from an upsert request.

    The system prompt and model selection have no dedicated manifest field,
    so they are carried in the manifest's free-form ``policy`` object per
    :class:`backend.agents.manifest.AgentManifest`.

    Args:
        agent_id: Fully qualified agent id (``namespace/name``) taken from the URL.
        payload: The requested agent configuration.

    Returns:
        A raw manifest document suitable for :func:`validate_agent_manifest`.
    """
    return {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": agent_id,
        "version": payload.version,
        "hostApi": "*",
        "capabilities": [{"id": "planning.decompose", "version": "1.0.0", "level": "primary"}],
        "io": {
            "contract": "autodev/custom-agent-io",
            "contractVersion": "1.0.0",
            "input": {"type": "object", "additionalProperties": True},
            "output": {"type": "object", "additionalProperties": True},
            "onInvalidOutput": "fail",
        },
        "entrypoint": {"runtime": "python", "ref": "backend.agents.custom:run"},
        "permissions": {"tools": list(payload.allowedTools)},
        "policy": {"systemPrompt": payload.systemPrompt, "model": payload.model},
        "displayName": payload.displayName,
        "description": payload.description,
    }


def _agent_extension_response(ref: AgentRef) -> AgentExtensionResponseV2:
    """Render an agent registration as the detailed extension response."""
    policy = ref.manifest.policy or {}
    return AgentExtensionResponseV2(
        item=_agent_item(ref),
        systemPrompt=str(policy.get("systemPrompt", "")),
        model=str(policy.get("model", "")),
        allowedTools=[tool.id for tool in ref.manifest.permissions.tools],
    )


@router.get("/agents/{agent_id:path}", response_model=AgentExtensionResponseV2)
def get_agent_extension(
    agent_id: str,
    version: str = Query(default="*", description="SemVer range to resolve, or '*' for the latest."),
    registry: AgentRegistry = Depends(get_agent_registry),
) -> AgentExtensionResponseV2:
    """Read a single agent extension's editable configuration.

    Args:
        agent_id: Fully qualified agent id.
        version: SemVer range to resolve.
        registry: Agent registry dependency.

    Returns:
        The agent's catalog item plus its system prompt, model, and allowed tools.
    """
    try:
        ref = registry.resolve(agent_id, version)
    except KeyError as exc:
        v2_error(404, str(exc))
    return _agent_extension_response(ref)


@router.put("/agents/{agent_id:path}", response_model=AgentExtensionResponseV2)
def upsert_agent_extension(
    agent_id: str,
    payload: AgentUpsertRequestV2,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> AgentExtensionResponseV2:
    """Create or edit an agent extension's system prompt, model, and allowed tools.

    This is a new surface with no legacy equivalent
    (``frontend/lib/api_ext.ts::listAgents`` is read-only). The manifest is
    validated against the existing agent manifest schema
    (:func:`backend.agents.manifest.validate_agent_manifest`) before being
    persisted through :meth:`~backend.agents.registry_v2.AgentRegistry.register`.

    Args:
        agent_id: Fully qualified agent id (``namespace/name``) taken from the URL.
        payload: The requested agent configuration.
        registry: Agent registry dependency.

    Returns:
        The persisted agent's catalog item plus its editable fields.
    """
    raw = _build_raw_manifest(agent_id, payload)
    result = validate_agent_manifest(raw)
    if not result.valid or result.manifest is None:
        v2_error(400, "; ".join(result.errors))
    ref = registry.register(result.manifest, plugin_id=CUSTOM_AGENT_PLUGIN_ID)
    return _agent_extension_response(ref)


__all__ = [
    "AgentExtensionResponseV2",
    "AgentUpsertRequestV2",
    "CUSTOM_AGENT_PLUGIN_ID",
    "ExtensionActionResponseV2",
    "ExtensionCatalogResponseV2",
    "ExtensionItemV2",
    "disable_extension",
    "enable_extension",
    "get_active_plugin_registry",
    "get_agent_extension",
    "get_agent_registry",
    "get_plugin_host",
    "get_skill_registry",
    "list_extensions",
    "router",
    "upsert_agent_extension",
]
