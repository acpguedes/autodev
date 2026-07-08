"use client";

import { useSyncExternalStore } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { createPanelHost } from "@/lib/panels/host";
import { panelRegistry, type PanelRegistry, type PanelSlotId } from "@/lib/panels/registry";
import { cn } from "@/lib/utils";

import { PanelErrorBoundary } from "./PanelErrorBoundary";

type PanelSlotOutletProps = {
  slot: PanelSlotId;
  registry?: PanelRegistry;
  className?: string;
};

/**
 * Mount point for plugin panels. Renders every enabled panel registered for
 * `slot`, each wrapped in the design-system Card chrome and an error
 * boundary so one faulty panel cannot break the page.
 */
export function PanelSlotOutlet({
  slot,
  registry = panelRegistry,
  className,
}: PanelSlotOutletProps) {
  useSyncExternalStore(registry.subscribe, registry.getSnapshot, registry.getSnapshot);
  const panels = registry.getForSlot(slot);

  if (panels.length === 0) {
    return null;
  }

  return (
    <section aria-label={`Plugin panels: ${slot}`} className={cn("flex flex-col gap-4", className)}>
      {panels.map(({ manifest, Component }) => (
        <Card key={manifest.id} data-panel-id={manifest.id} data-panel-slot={slot}>
          <CardHeader>
            <CardTitle>{manifest.title}</CardTitle>
            {manifest.description ? (
              <CardDescription>{manifest.description}</CardDescription>
            ) : null}
          </CardHeader>
          <CardContent>
            <PanelErrorBoundary panelId={manifest.id}>
              <Component manifest={manifest} host={createPanelHost(manifest)} />
            </PanelErrorBoundary>
          </CardContent>
        </Card>
      ))}
    </section>
  );
}

export default PanelSlotOutlet;
