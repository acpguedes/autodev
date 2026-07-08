"use client";

import { Badge } from "@/components/ui/badge";
import {
  panelRegistry,
  type PanelManifest,
  type PanelProps,
  type PanelRegistry,
} from "@/lib/panels/registry";

/**
 * Example panel published with the UI Extension Point (E10-S4 DoD). It only
 * uses design-system components and theme tokens — no hardcoded colors — so
 * it follows the active light/dark theme automatically.
 */
export const exampleRunSummaryManifest: PanelManifest = {
  id: "autodev/example.run-summary",
  title: "Run summary",
  slot: "run.detail.sidebar",
  contract: "^1.0",
  description: "Example plugin panel showing a compact summary of the latest run.",
};

export function ExampleRunSummaryPanel({ host }: PanelProps) {
  return (
    <dl className="grid grid-cols-2 gap-2 text-sm">
      <dt className="text-muted-foreground">Status</dt>
      <dd>
        <Badge variant="secondary">succeeded</Badge>
      </dd>
      <dt className="text-muted-foreground">Steps</dt>
      <dd className="font-medium">4 / 4</dd>
      <dt className="text-muted-foreground">Duration</dt>
      <dd className="font-medium">2m 14s</dd>
      <dt className="text-muted-foreground">Host contract</dt>
      <dd className="font-mono text-xs">{host.hostVersion}</dd>
    </dl>
  );
}

/** Idempotent registration of the built-in example panel. */
export function installExamplePanels(registry: PanelRegistry = panelRegistry) {
  if (!registry.get(exampleRunSummaryManifest.id)) {
    registry.register({
      manifest: exampleRunSummaryManifest,
      Component: ExampleRunSummaryPanel,
      source: "builtin",
    });
  }
}

export default ExampleRunSummaryPanel;
