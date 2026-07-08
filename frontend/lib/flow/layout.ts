/**
 * Deterministic layered auto-layout for the flow canvas (E10-S3-T1).
 *
 * Layers are assigned by breadth-first traversal from the entry node
 * (first-seen depth), rows within a layer follow node declaration order —
 * the same manifest always renders in the same place.
 */

import type { FlowManifest } from "./types";

export const NODE_WIDTH = 192;
export const NODE_HEIGHT = 76;
export const H_GAP = 96;
export const V_GAP = 48;
export const CANVAS_PADDING = 24;

export type NodePosition = { x: number; y: number };

export type FlowLayout = {
  positions: Record<string, NodePosition>;
  width: number;
  height: number;
};

export function layoutFlow(manifest: FlowManifest): FlowLayout {
  const nodes = manifest.nodes;
  if (nodes.length === 0) {
    return { positions: {}, width: 2 * CANVAS_PADDING, height: 2 * CANVAS_PADDING };
  }

  const declarationIndex = new Map(nodes.map((node, index) => [node.id, index]));
  const outgoing = new Map<string, string[]>();
  const incoming = new Map<string, number>();
  for (const edge of manifest.edges) {
    if (!declarationIndex.has(edge.from) || !declarationIndex.has(edge.to)) {
      continue;
    }
    outgoing.set(edge.from, [...(outgoing.get(edge.from) ?? []), edge.to]);
    incoming.set(edge.to, (incoming.get(edge.to) ?? 0) + 1);
  }

  // BFS roots: nodes without incoming edges, else the first declared node.
  const roots = nodes.filter((node) => !incoming.has(node.id)).map((node) => node.id);
  if (roots.length === 0) {
    roots.push(nodes[0].id);
  }

  const layerOf = new Map<string, number>();
  const queue: Array<{ id: string; layer: number }> = roots.map((id) => ({ id, layer: 0 }));
  roots.forEach((id) => layerOf.set(id, 0));
  while (queue.length > 0) {
    const { id, layer } = queue.shift() as { id: string; layer: number };
    const targets = [...(outgoing.get(id) ?? [])].sort(
      (a, b) => (declarationIndex.get(a) ?? 0) - (declarationIndex.get(b) ?? 0)
    );
    for (const target of targets) {
      if (!layerOf.has(target)) {
        layerOf.set(target, layer + 1);
        queue.push({ id: target, layer: layer + 1 });
      }
    }
  }
  // Disconnected nodes (invalid graphs still need to render): layer 0.
  for (const node of nodes) {
    if (!layerOf.has(node.id)) {
      layerOf.set(node.id, 0);
    }
  }

  const rows = new Map<number, number>();
  const positions: Record<string, NodePosition> = {};
  for (const node of nodes) {
    const layer = layerOf.get(node.id) as number;
    const row = rows.get(layer) ?? 0;
    rows.set(layer, row + 1);
    positions[node.id] = {
      x: CANVAS_PADDING + layer * (NODE_WIDTH + H_GAP),
      y: CANVAS_PADDING + row * (NODE_HEIGHT + V_GAP),
    };
  }

  const maxLayer = Math.max(...Array.from(rows.keys()));
  const maxRows = Math.max(...Array.from(rows.values()));
  return {
    positions,
    width: 2 * CANVAS_PADDING + (maxLayer + 1) * NODE_WIDTH + maxLayer * H_GAP,
    height: 2 * CANVAS_PADDING + maxRows * NODE_HEIGHT + (maxRows - 1) * V_GAP,
  };
}
