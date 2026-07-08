// Panel discovery via the Plugin Host bridge (E10-S4-T3).
//
// The Plugin Host (E1) hands the Web UI one `PluginPanelBundle` per loaded
// plugin that declares a `ui-panel` extension point. Installation is
// fault-isolated: a bundle or panel that fails validation is reported and
// skipped — it can never prevent other panels (or the app) from loading.
// Remote entry-module loading is E1 integration work; bundles arrive through
// a local module map until then (see frontend/docs/pluggable-panels.md).

import {
  isContractCompatible,
  validatePanelManifest,
  type PanelComponent,
  type PanelRegistry,
} from "./registry";

export type PanelContribution = {
  /** Untrusted manifest as declared by the plugin. */
  manifest: unknown;
  Component: PanelComponent;
};

export type PluginPanelBundle = {
  /** Plugin id as known by the Plugin Host, e.g. "acme/plugin-jira". */
  pluginId: string;
  /** Optional plugin `hostApi` compatibility range (SemVer). */
  hostApi?: string;
  panels: PanelContribution[];
};

export type PanelDiscoveryEntry = {
  pluginId: string;
  panelId: string | null;
  ok: boolean;
  errors: string[];
};

export type PanelDiscoveryReport = {
  installed: number;
  rejected: number;
  entries: PanelDiscoveryEntry[];
};

/** Validates and registers plugin-contributed panels. Never throws. */
export function installPluginPanels(
  registry: PanelRegistry,
  bundles: PluginPanelBundle[]
): PanelDiscoveryReport {
  const entries: PanelDiscoveryEntry[] = [];

  for (const bundle of bundles) {
    if (bundle.hostApi !== undefined && !isContractCompatible(bundle.hostApi)) {
      entries.push({
        pluginId: bundle.pluginId,
        panelId: null,
        ok: false,
        errors: [`plugin hostApi "${bundle.hostApi}" is not compatible with this host`],
      });
      continue;
    }

    for (const contribution of bundle.panels) {
      const validated = validatePanelManifest(contribution.manifest);
      if (!validated.ok) {
        entries.push({
          pluginId: bundle.pluginId,
          panelId: null,
          ok: false,
          errors: validated.errors,
        });
        continue;
      }
      const result = registry.register({
        manifest: validated.manifest,
        Component: contribution.Component,
        source: bundle.pluginId,
      });
      entries.push({
        pluginId: bundle.pluginId,
        panelId: validated.manifest.id,
        ok: result.ok,
        errors: result.ok ? [] : result.errors,
      });
    }
  }

  const installed = entries.filter((entry) => entry.ok).length;
  return { installed, rejected: entries.length - installed, entries };
}
