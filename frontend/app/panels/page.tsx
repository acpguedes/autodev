"use client";

import { useEffect } from "react";

import ChatLayout from "../../components/ChatLayout";
import { installExamplePanels } from "../../components/panels/ExampleRunSummaryPanel";
import { PanelManager } from "../../components/panels/PanelManager";
import { PanelSlotOutlet } from "../../components/panels/PanelSlotOutlet";
import { PANEL_SLOTS } from "../../lib/panels/registry";

export default function PanelsPage() {
  // Built-in example panel; plugin panels arrive via the Plugin Host bridge
  // (lib/panels/discovery.ts). Registered client-side to keep SSR clean.
  useEffect(() => {
    installExamplePanels();
  }, []);

  return (
    <ChatLayout currentView="panels">
      <div className="flex flex-col gap-6 p-6">
        <header>
          <p className="eyebrow">UI Extension Points</p>
          <h2>Pluggable panels</h2>
          <p className="subtitle">
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
    </ChatLayout>
  );
}
