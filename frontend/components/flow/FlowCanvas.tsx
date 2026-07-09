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

export type CanvasPosition = { x: number; y: number };

type FlowCanvasProps = {
  manifest: FlowManifest;
  selectedNodeId: string | null;
  /** Nodes with validation errors — rendered with a destructive border. */
  errorNodeIds: ReadonlySet<string>;
  onSelectNode: (nodeId: string) => void;
  /**
   * Manual position overrides (from dragging or keyboard nudging), keyed by
   * node id. Falls back to the deterministic auto layout for any node
   * without an override. Positions are editor-only state, never persisted
   * to the `flow.yaml` manifest.
   */
  positions?: Readonly<Record<string, CanvasPosition>>;
  /** Invoked while a node is dragged (pointer) or nudged (arrow keys) to a new position. */
  onNodeMove?: (nodeId: string, position: CanvasPosition) => void;
  /**
   * Invoked when the operator connects two nodes via the per-side connector
   * dots, either by dragging from one dot to another or by clicking a dot
   * to designate the source and then clicking a dot on the target node.
   */
  onConnectNodes?: (fromId: string, toId: string) => void;
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

const CONNECTOR_SIDES = ["top", "right", "bottom", "left"] as const;
type ConnectorSide = (typeof CONNECTOR_SIDES)[number];

const CONNECTOR_DOT_STYLE: Record<ConnectorSide, React.CSSProperties> = {
  top: { top: -5, left: "50%", transform: "translateX(-50%)" },
  right: { top: "50%", right: -5, transform: "translateY(-50%)" },
  bottom: { bottom: -5, left: "50%", transform: "translateX(-50%)" },
  left: { top: "50%", left: -5, transform: "translateY(-50%)" },
};

const ARROW_KEYS: Record<string, CanvasPosition> = {
  ArrowLeft: { x: -1, y: 0 },
  ArrowRight: { x: 1, y: 0 },
  ArrowUp: { x: 0, y: -1 },
  ArrowDown: { x: 0, y: 1 },
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function guardText(edge: FlowEdge): string | null {
  if (edge.on !== undefined) {
    return `on: ${edge.on}`;
  }
  if (edge.when !== undefined) {
    const compact = edge.when.replace(/^\{\{\s*|\s*\}\}$/g, "").trim();
    // The prototype favors plain "yes"/"no" branch labels for boolean guards.
    if (compact === "true") {
      return "yes";
    }
    if (compact === "false") {
      return "no";
    }
    return compact.length > 28 ? `${compact.slice(0, 25)}…` : compact;
  }
  return null;
}

function edgePath(
  from: CanvasPosition,
  to: CanvasPosition
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
 * SVG + DOM flow canvas (E10-S3-T1, realigned for E17-S6). Nodes are real
 * buttons in deterministic layout order, so the whole graph is
 * keyboard-navigable (Tab / Enter) and screen-reader friendly; edges are
 * also announced through an sr-only list.
 *
 * When `onNodeMove` is supplied, nodes can be repositioned by pointer drag
 * or, with a node focused, the arrow keys (Shift for a larger step). When
 * `onConnectNodes` is supplied, each node grows four small connector dots
 * (one per side) that create an edge when dragged onto another node's dot,
 * or when clicked to designate a source and then clicked again on a target.
 */
export function FlowCanvas({
  manifest,
  selectedNodeId,
  errorNodeIds,
  onSelectNode,
  positions,
  onNodeMove,
  onConnectNodes,
}: FlowCanvasProps) {
  const layout = React.useMemo(() => layoutFlow(manifest), [manifest]);
  const effectivePositions = React.useMemo<Record<string, CanvasPosition>>(
    () => ({ ...layout.positions, ...positions }),
    [layout.positions, positions]
  );

  const [pendingConnectFrom, setPendingConnectFrom] = React.useState<string | null>(null);
  const dragRef = React.useRef<{
    nodeId: string;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);

  const maxX = Math.max(0, layout.width - NODE_WIDTH);
  const maxY = Math.max(0, layout.height - NODE_HEIGHT);

  function handleNodePointerDown(
    event: React.PointerEvent<HTMLButtonElement>,
    nodeId: string,
    position: CanvasPosition
  ) {
    if (!onNodeMove) {
      return;
    }
    dragRef.current = {
      nodeId,
      startX: event.clientX,
      startY: event.clientY,
      originX: position.x,
      originY: position.y,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleNodePointerMove(event: React.PointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    if (!drag || !onNodeMove) {
      return;
    }
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    onNodeMove(drag.nodeId, {
      x: clamp(drag.originX + dx, 0, maxX),
      y: clamp(drag.originY + dy, 0, maxY),
    });
  }

  function handleNodePointerUp() {
    dragRef.current = null;
  }

  function handleNodeKeyDown(
    event: React.KeyboardEvent<HTMLButtonElement>,
    nodeId: string,
    position: CanvasPosition
  ) {
    const nudge = ARROW_KEYS[event.key];
    if (!nudge || !onNodeMove) {
      return;
    }
    event.preventDefault();
    const step = event.shiftKey ? 24 : 8;
    onNodeMove(nodeId, {
      x: clamp(position.x + nudge.x * step, 0, maxX),
      y: clamp(position.y + nudge.y * step, 0, maxY),
    });
  }

  function handleDotActivate(nodeId: string) {
    if (!onConnectNodes) {
      return;
    }
    if (pendingConnectFrom === null) {
      setPendingConnectFrom(nodeId);
      return;
    }
    if (pendingConnectFrom === nodeId) {
      setPendingConnectFrom(null);
      return;
    }
    onConnectNodes(pendingConnectFrom, nodeId);
    setPendingConnectFrom(null);
  }

  function handleDotDrop(event: React.DragEvent<HTMLButtonElement>, nodeId: string) {
    event.preventDefault();
    const fromId = event.dataTransfer.getData("text/plain");
    if (fromId && fromId !== nodeId) {
      onConnectNodes?.(fromId, nodeId);
    }
    setPendingConnectFrom(null);
  }

  return (
    <div
      role="group"
      aria-label="Flow graph canvas"
      className="h-full w-full overflow-auto rounded-ds-lg border border-ds-line bg-ds-bg-2"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setPendingConnectFrom(null);
        }
      }}
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
        style={{
          width: layout.width,
          height: layout.height,
          minWidth: "100%",
          minHeight: "100%",
          // Dotted-grid backdrop from the redesign prototype (§5.4).
          backgroundImage:
            "radial-gradient(circle, hsl(var(--ds-line-strong) / 0.7) 1px, transparent 1px)",
          backgroundSize: "24px 24px",
        }}
      >
        <svg
          aria-hidden="true"
          className="absolute inset-0 text-ds-fg-3"
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
            const from = effectivePositions[edge.from];
            const to = effectivePositions[edge.to];
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
          const position = effectivePositions[node.id];
          if (!position) {
            return null;
          }
          const selected = node.id === selectedNodeId;
          const hasError = errorNodeIds.has(node.id);
          const isPendingSource = pendingConnectFrom === node.id;
          return (
            <div
              key={node.id}
              className="absolute"
              style={{ left: position.x, top: position.y, width: NODE_WIDTH, height: NODE_HEIGHT }}
            >
              <button
                type="button"
                aria-pressed={selected}
                aria-label={`${node.type} node ${node.label ?? node.id}${
                  hasError ? " (has validation issues)" : ""
                }`}
                onClick={() => onSelectNode(node.id)}
                onPointerDown={(event) => handleNodePointerDown(event, node.id, position)}
                onPointerMove={handleNodePointerMove}
                onPointerUp={handleNodePointerUp}
                onKeyDown={(event) => handleNodeKeyDown(event, node.id, position)}
                className={cn(
                  "absolute inset-0 flex flex-col items-start justify-center gap-1 rounded-ds-md border bg-ds-bg-3 px-3 py-2 text-left shadow-ds-sm transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent",
                  onNodeMove ? "cursor-grab touch-none active:cursor-grabbing" : undefined,
                  hasError ? "border-ds-danger" : "border-ds-line",
                  selected && "ring-2 ring-ds-accent"
                )}
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
                <span className="w-full truncate font-mono text-sm text-ds-fg">
                  {node.label ?? node.id}
                </span>
                {node.ref ? (
                  <span className="w-full truncate text-xs text-ds-fg-2">{node.ref}</span>
                ) : null}
              </button>
              {onConnectNodes
                ? CONNECTOR_SIDES.map((side) => (
                    <button
                      key={side}
                      type="button"
                      draggable
                      onDragStart={(event) => {
                        event.dataTransfer.setData("text/plain", node.id);
                        event.dataTransfer.effectAllowed = "link";
                      }}
                      onDragOver={(event) => {
                        event.preventDefault();
                        event.dataTransfer.dropEffect = "link";
                      }}
                      onDrop={(event) => handleDotDrop(event, node.id)}
                      onClick={(event) => {
                        event.stopPropagation();
                        handleDotActivate(node.id);
                      }}
                      aria-label={
                        isPendingSource
                          ? `Cancel pending connection from ${node.label ?? node.id}`
                          : pendingConnectFrom
                            ? `Connect from ${pendingConnectFrom} to ${node.label ?? node.id}`
                            : `Start a connection from ${node.label ?? node.id} (${side})`
                      }
                      title="Drag to another node's dot, or click to connect"
                      className={cn(
                        "absolute z-10 h-2.5 w-2.5 rounded-ds-full border transition-colors",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent",
                        isPendingSource
                          ? "border-ds-accent bg-ds-accent"
                          : "border-ds-line-strong bg-ds-bg-2 hover:border-ds-accent hover:bg-ds-accent/40"
                      )}
                      style={CONNECTOR_DOT_STYLE[side]}
                    />
                  ))
                : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
