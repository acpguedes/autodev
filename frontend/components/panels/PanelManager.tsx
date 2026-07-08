"use client";

import { useSyncExternalStore } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { panelRegistry, type PanelRegistry } from "@/lib/panels/registry";

type PanelManagerProps = {
  registry?: PanelRegistry;
};

/** Lets the user enable/disable registered plugin panels (persisted locally). */
export function PanelManager({ registry = panelRegistry }: PanelManagerProps) {
  useSyncExternalStore(registry.subscribe, registry.getSnapshot, registry.getSnapshot);
  const panels = registry.list();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Plugin panels</CardTitle>
        <CardDescription>
          Enable or disable panels contributed by plugins. Choices persist in this
          browser.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {panels.length === 0 ? (
          <p className="text-sm text-muted-foreground">No panels registered.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {panels.map((panel) => (
              <li
                key={panel.manifest.id}
                className="flex items-start justify-between gap-4 rounded-md border p-3"
              >
                <div className="flex flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{panel.manifest.title}</span>
                    <Badge variant="secondary">{panel.manifest.slot}</Badge>
                    {panel.source ? <Badge variant="outline">{panel.source}</Badge> : null}
                  </div>
                  {panel.manifest.description ? (
                    <p className="text-sm text-muted-foreground">
                      {panel.manifest.description}
                    </p>
                  ) : null}
                  <p className="text-xs text-muted-foreground">
                    {panel.manifest.id} · contract {panel.manifest.contract} · network:{" "}
                    {panel.manifest.permissions?.network?.egress?.join(", ") || "none"}
                  </p>
                </div>
                <label className="flex shrink-0 items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-input"
                    aria-label={`Enable ${panel.manifest.title}`}
                    checked={panel.enabled}
                    onChange={(event) =>
                      registry.setEnabled(panel.manifest.id, event.target.checked)
                    }
                  />
                  Enabled
                </label>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default PanelManager;
