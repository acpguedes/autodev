"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import {
  NODE_HEIGHT,
  NODE_WIDTH,
  layoutFlow,
} from "@/lib/flow/layout";
import { isGuarded, type FlowEdge, type FlowManifest } from "@/lib/flow/types";
import { cn } from "@/lib/utils";

type FlowCanvasProps = {
  manifest: FlowManifest;
  selectedNodeId: string | null;
  /** Nodes with validation errors — rendered with a destructive border. */
  errorNodeIds: ReadonlySet<string>;
  onSelectNode: (nodeId: string) => void;
};

const TYPE_BADGE_VARIANT: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  agent: "default",
  skill: "secondary",
  tool: "outline",
  conditional: "secondary",
  human: "default",
  subflow: "outline",
  map: "secondary",
};

function guardText(edge: FlowEdge): string | null {
  if (edge.on !== undefined) {
    return `on: ${edge.on}`;
  }
  if (edge.when !== undefined) {
    const compact = edge.when.replace(/^\{\{\s*|\s*\}\}$/g, "").trim();
    return compact.length > 28 ? `${compact.slice(0, 25)}…` : compact;
  }
  return null;
}

function edgePath(
  from: { x: number; y: number },
  to: { x: number; y: number }
): { d: string; labelX: number; labelY: number } {
  const x1 = from.x + NODE_WIDTH;
  const y1 = from.y + NODE_HEIGHT / 2;
  const x2 = to.x;
  const y2 = to.y + NODE_HEIGHT / 2;

  if (x2 >= x1) {
    // Forward edge: horizontal cubic curve.
    const dx = Math.max((x2 - x1) / 2, 24);
    return {
      d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
      labelX: (x1 + x2) / 2,
      labelY: (y1 + y2) / 2 - 6,
    };
  }

  // Back edge (rework loop): route below both nodes.
  const bottom = Math.max(y1, y2) + NODE_HEIGHT;
  return {
    d: `M ${x1} ${y1} C ${x1 + 48} ${bottom}, ${x2 - 48} ${bottom}, ${x2} ${y2}`,
    labelX: (x1 + x2) / 2,
    labelY: bottom - 6,
  };
}

/**
 * SVG + DOM flow canvas (E10-S3-T1). Nodes are real buttons in deterministic
 * layout order, so the whole graph is keyboard-navigable (Tab / Enter) and
 * screen-reader friendly; edges are also announced through an sr-only list.
 */
export function FlowCanvas({
  manifest,
  selectedNodeId,
  errorNodeIds,
  onSelectNode,
}: FlowCanvasProps) {
  const layout = React.useMemo(() => layoutFlow(manifest), [manifest]);

  return (
    <div
      role="group"
      aria-label="Flow graph canvas"
      className="h-full w-full overflow-auto rounded-lg border border-border bg-muted/30"
    >
      <p className="sr-only">
        {manifest.edges.length === 0
          ? "The flow has no edges."
          : `Edges: ${manifest.edges
              .map((edge) => {
                const guard = guardText(edge);
                return `${edge.from} to ${edge.to}${guard ? ` (${guard})` : ""}`;
              })
              .join("; ")}.`}
      </p>
      <div
        className="relative"
        style={{ width: layout.width, height: layout.height, minWidth: "100%", minHeight: "100%" }}
      >
        <svg
          aria-hidden="true"
          className="absolute inset-0 text-muted-foreground"
          width={layout.width}
          height={layout.height}
        >
          <defs>
            <marker
              id="flow-edge-arrow"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 8 4 L 0 8 z" fill="currentColor" />
            </marker>
          </defs>
          {manifest.edges.map((edge, index) => {
            const from = layout.positions[edge.from];
            const to = layout.positions[edge.to];
            if (!from || !to) {
              return null;
            }
            const { d, labelX, labelY } = edgePath(from, to);
            const label = guardText(edge);
            return (
              <g key={`${edge.from}->${edge.to}#${index}`}>
                <path
                  d={d}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.5}
                  strokeDasharray={isGuarded(edge) ? "6 4" : undefined}
                  markerEnd="url(#flow-edge-arrow)"
                />
                {label ? (
                  <text
                    x={labelX}
                    y={labelY}
                    textAnchor="middle"
                    className="fill-current font-mono text-[10px]"
                  >
                    {label}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
        {manifest.nodes.map((node) => {
          const position = layout.positions[node.id];
          if (!position) {
            return null;
          }
          const selected = node.id === selectedNodeId;
          const hasError = errorNodeIds.has(node.id);
          return (
            <button
              key={node.id}
              type="button"
              aria-pressed={selected}
              aria-label={`${node.type} node ${node.id}${hasError ? " (has validation issues)" : ""}`}
              onClick={() => onSelectNode(node.id)}
              className={cn(
                "absolute flex flex-col items-start justify-center gap-1 rounded-lg border bg-background px-3 py-2 text-left shadow-sm transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                hasError ? "border-destructive" : "border-border",
                selected && "ring-2 ring-ring"
              )}
              style={{
                left: position.x,
                top: position.y,
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
              }}
            >
              <span className="flex w-full items-center justify-between gap-2">
                <Badge variant={TYPE_BADGE_VARIANT[node.type] ?? "outline"}>
                  {node.type}
                </Badge>
                {hasError ? (
                  <Badge variant="destructive" aria-hidden="true">
                    !
                  </Badge>
                ) : null}
              </span>
              <span className="w-full truncate font-mono text-sm text-foreground">
                {node.id}
              </span>
              {node.ref ? (
                <span className="w-full truncate text-xs text-muted-foreground">
                  {node.ref}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
