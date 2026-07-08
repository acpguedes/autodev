"use client";

import { useEffect } from "react";

import { installExamplePanels } from "../../components/panels/ExampleRunSummaryPanel";
import { PanelManager } from "../../components/panels/PanelManager";
import { PanelSlotOutlet } from "../../components/panels/PanelSlotOutlet";
import { PANEL_SLOTS } from "../../lib/panels/registry";
import { useShellHeader } from "@/components/shell/ShellProvider";

export default function PanelsPage() {
  useShellHeader({
    title: "Panels",
    subtitle: "Pluggable UI panels contributed by plugins.",
  });

  // Built-in example panel; plugin panels arrive via the Plugin Host bridge
  // (lib/panels/discovery.ts). Registered client-side to keep SSR clean.
  useEffect(() => {
    installExamplePanels();
  }, []);

  return (
    <div className="flex flex-col gap-6 p-6">
        <header className="flex flex-col gap-2">
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">
            UI Extension Points
          </p>
          <h2 className="font-serif text-2xl font-semibold text-ds-fg">Pluggable panels</h2>
          <p className="text-sm text-ds-fg-3">
            Panels contributed by plugins, mounted into registered slots. Disable a
            panel to remove it from every slot.
          </p>
        </header>

        <PanelManager />

        {PANEL_SLOTS.map((slot) => (
          <section key={slot} aria-labelledby={`slot-${slot}`}>
            <h3 id={`slot-${slot}`} className="mb-2 text-sm font-semibold text-muted-foreground">
              Slot: {slot}
            </h3>
            <PanelSlotOutlet slot={slot} />
          </section>
        ))}
    </div>
  );
}
