// Shared display helpers for the Extensions hub (E17-S5). Every extension
// kind (agent/skill/plugin/mcp) returns its manifest facts inside the
// catalog item's freeform `detail` bag (see `_agent_item`/`_skill_item`/
// `_plugin_item`/`_mcp_item` in `backend/api/routers/extensions_v2.py`), so
// these helpers centralize the narrow, defensive reads used by the card and
// detail dialog components instead of repeating `detail as ...` casts.

import type { ExtensionItemV2, ExtensionKindV2 } from "@/lib/api_v2";

/** Human label for each extension kind, used in tab triggers and headings. */
export const EXTENSION_KIND_LABELS: Record<ExtensionKindV2, string> = {
  agent: "Agents",
  skill: "Skills",
  plugin: "Plugins",
  mcp: "MCP",
};

/** Manifest file conventionally associated with each extension kind. */
export const EXTENSION_KIND_MANIFEST: Record<ExtensionKindV2, string> = {
  agent: "agent.yaml",
  skill: "skill.yaml",
  plugin: "plugin.yaml",
  mcp: "mcp.yaml",
};

/**
 * Read the manifest version out of an extension item's `detail` bag.
 *
 * @param item - Catalog item returned by `GET /v2/extensions`.
 * @returns The version string, or `null` when the catalog did not report one.
 */
export function extensionVersion(item: ExtensionItemV2): string | null {
  const value = item.detail?.["version"];
  return typeof value === "string" && value.length > 0 ? value : null;
}

/**
 * Build a short, kind-appropriate description line for an extension card
 * from whatever manifest facts the catalog exposed for that kind.
 *
 * `agent` and `skill` items carry list-shaped facts (`capabilities`,
 * `triggers`); `plugin` items carry `extensionPoints`; `mcp` items are
 * per-skill exposure entries and use the owning plugin as their summary.
 * None of the four kinds return a free-text `description` field from the
 * backend today, so this derives the closest available summary instead of
 * showing nothing.
 *
 * @param kind - The extension's kind.
 * @param item - Catalog item returned by `GET /v2/extensions`.
 * @returns A one-line description, or `null` when no manifest facts apply.
 */
export function extensionDescription(
  kind: ExtensionKindV2,
  item: ExtensionItemV2
): string | null {
  if (kind === "agent" || kind === "skill") {
    const key = kind === "agent" ? "capabilities" : "triggers";
    const values = item.detail?.[key];
    if (Array.isArray(values) && values.length > 0) {
      const label = kind === "agent" ? "Capabilities" : "Triggers";
      return `${label}: ${values.map(String).join(", ")}`;
    }
    return null;
  }
  if (kind === "plugin") {
    const points = item.detail?.["extensionPoints"];
    if (Array.isArray(points) && points.length > 0) {
      return `Extension points: ${points.map(String).join(", ")}`;
    }
    return null;
  }
  // mcp: one catalog entry per exposed skill; the plugin id (when present)
  // is the most useful at-a-glance context.
  return item.pluginId ? `Exposed via plugin ${item.pluginId}` : "Standalone skill exposure";
}
