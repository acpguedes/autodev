"use client";

import { Button } from "@/components/ui/button";
import type { FlowCatalogItemV2 } from "@/lib/api_v2";
import {
  AGENT_PALETTE_ITEMS,
  CONTROL_PALETTE_ITEMS,
  type AgentPaletteItem,
  type ControlPaletteItem,
} from "@/lib/flow/paletteItems";
import { cn } from "@/lib/utils";

export type FlowPaletteProps = {
  /** Flows library listing (read-only); empty while loading or on error. */
  catalog: FlowCatalogItemV2[];
  catalogLoading?: boolean;
  catalogError?: string | null;
  /** Id of the node currently selected on the canvas, if any. */
  selectedNodeId: string | null;
  onInsertAgent: (item: AgentPaletteItem) => void;
  onInsertControl: (item: ControlPaletteItem) => void;
  onNewFlow: () => void;
  /**
   * Disables the "Agents"/"Flow control" insert buttons — set when the
   * flow.yaml document does not currently parse, so there is no manifest to
   * insert a node into (the canvas shows a matching placeholder in that
   * state). "New blank flow" stays enabled as the recovery action.
   */
  insertDisabled?: boolean;
};

function PaletteButton({
  label,
  description,
  onClick,
  disabled,
}: {
  label: string;
  description: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={description}
      className={cn(
        "flex w-full flex-col items-start gap-0.5 rounded-ds-md border border-ds-line bg-ds-bg-2 px-3 py-2 text-left transition-colors",
        "hover:border-ds-accent hover:bg-ds-bg-3",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent",
        "disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-ds-line disabled:hover:bg-ds-bg-2"
      )}
    >
      <span className="text-sm font-medium text-ds-fg">{label}</span>
      <span className="w-full truncate text-xs text-ds-fg-2">{description}</span>
    </button>
  );
}

/**
 * Left-column palette for the flow builder (E17-S6): the flows library
 * (read-only, plus "New"), the eight built-in agent types, and the
 * flow-control blocks (Conditional, Loop, Human approval, Parallel,
 * Prompt/Step, Start, End).
 *
 * Clicking an Agents/Flow-control entry inserts a node — connected by an
 * edge from the currently selected node when one is selected, or
 * standalone otherwise.
 */
export function FlowPalette({
  catalog,
  catalogLoading,
  catalogError,
  selectedNodeId,
  onInsertAgent,
  onInsertControl,
  onNewFlow,
  insertDisabled,
}: FlowPaletteProps) {
  return (
    <div
      role="group"
      aria-label="Flow palette"
      className="flex h-full flex-col gap-5 overflow-y-auto rounded-ds-lg border border-ds-line bg-ds-bg-2 p-3 shadow-ds-sm"
    >
      <section className="flex flex-col gap-2">
        <h3 className="font-serif text-sm font-semibold text-ds-fg">Flows library</h3>
        <Button type="button" variant="secondary" size="sm" onClick={onNewFlow}>
          New blank flow
        </Button>
        {catalogLoading ? (
          <p className="text-xs text-ds-fg-2">Loading…</p>
        ) : catalogError ? (
          <p className="text-xs text-ds-danger">{catalogError}</p>
        ) : catalog.length === 0 ? (
          <p className="text-xs text-ds-fg-2">No flows registered yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {catalog.map((flow) => (
              <li
                key={`${flow.id}@${flow.version}`}
                className="truncate rounded-ds-sm border border-ds-line bg-ds-bg px-2 py-1 text-xs text-ds-fg-2"
                title={flow.description ?? flow.id}
              >
                {flow.name ?? flow.id}
                <span className="ml-1 text-ds-fg-2">v{flow.version}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-serif text-sm font-semibold text-ds-fg">Agents</h3>
        <p className="text-xs text-ds-fg-2">
          {insertDisabled
            ? "Fix the flow.yaml parse errors to insert nodes."
            : selectedNodeId
              ? `Connects from "${selectedNodeId}".`
              : "Adds a standalone node."}
        </p>
        <div className="flex flex-col gap-1.5">
          {AGENT_PALETTE_ITEMS.map((item) => (
            <PaletteButton
              key={item.id}
              label={item.label}
              description={item.description}
              onClick={() => onInsertAgent(item)}
              disabled={insertDisabled}
            />
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-serif text-sm font-semibold text-ds-fg">Flow control</h3>
        <div className="flex flex-col gap-1.5">
          {CONTROL_PALETTE_ITEMS.map((item) => (
            <PaletteButton
              key={item.id}
              label={item.label}
              description={item.description}
              onClick={() => onInsertControl(item)}
              disabled={insertDisabled}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
