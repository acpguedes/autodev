"use client";

import * as React from "react";

import { FlowCanvas, type CanvasPosition } from "@/components/flow/FlowCanvas";
import { FlowPalette } from "@/components/flow/FlowPalette";
import { NodeInspector } from "@/components/flow/NodeInspector";
import { ValidationPanel } from "@/components/flow/ValidationPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  listFlowsV2,
  validateFlowV2,
  type FlowCatalogItemV2,
} from "@/lib/api_v2";
import { createBlankFlow, SAMPLE_FLOW_YAML } from "@/lib/flow/sample";
import type { AgentPaletteItem, ControlPaletteItem } from "@/lib/flow/paletteItems";
import { KEBAB_CASE, type FlowEdge, type FlowManifest, type FlowNode } from "@/lib/flow/types";
import { validateFlow, type ValidationIssue } from "@/lib/flow/validate";
import { parseFlowYaml, serializeFlowYaml } from "@/lib/flow/yaml";
import { toast } from "@/lib/use-toast";
import { cn } from "@/lib/utils";

type FlowEditorProps = {
  /** Initial flow.yaml document; defaults to the feature-delivery sample. */
  initialYaml?: string;
};

/** Rewrite `nodes.<old>` / `nodes['<old>']` references inside expressions. */
function replaceNodeRefs(value: unknown, oldId: string, nextId: string): unknown {
  if (typeof value === "string") {
    return value
      .split(`nodes.${oldId}.`)
      .join(`nodes.${nextId}.`)
      .split(`nodes['${oldId}']`)
      .join(`nodes['${nextId}']`);
  }
  if (Array.isArray(value)) {
    return value.map((entry) => replaceNodeRefs(entry, oldId, nextId));
  }
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [key, replaceNodeRefs(entry, oldId, nextId)])
    );
  }
  return value;
}

function withPatch<T extends Record<string, unknown>>(base: T, patch: Partial<T>): T {
  const next: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) {
      delete next[key];
    } else {
      next[key] = value;
    }
  }
  return next as T;
}

/** Drops a single key from a positions record, returning the same reference when absent. */
function omitPosition(
  positions: Record<string, CanvasPosition>,
  nodeId: string
): Record<string, CanvasPosition> {
  if (!(nodeId in positions)) {
    return positions;
  }
  const next = { ...positions };
  delete next[nodeId];
  return next;
}

/** Triggers a browser download of the canonical `flow.yaml` document. */
function downloadFlowYaml(yamlText: string): void {
  const blob = new Blob([yamlText], { type: "text/yaml" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "flow.yaml";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Visual flow editor (E10-S3, realigned for E17-S6 into the "Execution
 * Control Center" three-column shell): palette + graph canvas + node
 * inspector, with deterministic flow.yaml round-trip and real-time
 * validation.
 */
export function FlowEditor({ initialYaml }: FlowEditorProps) {
  const [initial] = React.useState(() => {
    const text = initialYaml ?? SAMPLE_FLOW_YAML;
    const parsed = parseFlowYaml(text);
    return { text, parsed };
  });
  const [yamlText, setYamlText] = React.useState(initial.text);
  const [manifest, setManifest] = React.useState<FlowManifest | null>(
    initial.parsed.ok ? initial.parsed.manifest : null
  );
  const [parseErrors, setParseErrors] = React.useState<string[]>(
    initial.parsed.ok ? [] : initial.parsed.errors
  );
  const [selectedNodeId, setSelectedNodeId] = React.useState<string | null>(null);
  const [activeTab, setActiveTab] = React.useState("inspector");
  const [positions, setPositions] = React.useState<Record<string, CanvasPosition>>({});
  const [saving, setSaving] = React.useState(false);
  const [catalog, setCatalog] = React.useState<FlowCatalogItemV2[]>([]);
  const [catalogLoading, setCatalogLoading] = React.useState(true);
  const [catalogError, setCatalogError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    listFlowsV2()
      .then((result) => {
        if (!cancelled) {
          setCatalog(result.flows);
          setCatalogLoading(false);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setCatalogError(
            error instanceof Error ? error.message : "Failed to load the flows library."
          );
          setCatalogLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const issues: ValidationIssue[] = React.useMemo(
    () => (manifest ? validateFlow(manifest) : []),
    [manifest]
  );
  const errorNodeIds = React.useMemo(
    () =>
      new Set(issues.map((issue) => issue.nodeId).filter((id): id is string => id !== undefined)),
    [issues]
  );
  const issueCount = parseErrors.length + issues.length;

  /** Apply a visual edit: update the manifest and regenerate canonical YAML. */
  const applyManifest = React.useCallback((next: FlowManifest) => {
    setManifest(next);
    setYamlText(serializeFlowYaml(next));
    setParseErrors([]);
  }, []);

  const handleYamlChange = (text: string) => {
    setYamlText(text);
    const parsed = parseFlowYaml(text);
    if (parsed.ok) {
      setManifest(parsed.manifest);
      setParseErrors([]);
    } else {
      setParseErrors(parsed.errors);
    }
  };

  const selectNode = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    setActiveTab("inspector");
  };

  const updateNode = (nodeId: string, patch: Partial<FlowNode>) => {
    if (!manifest) return;
    applyManifest({
      ...manifest,
      nodes: manifest.nodes.map((node) =>
        node.id === nodeId ? withPatch(node, patch) : node
      ),
    });
  };

  const renameNode = (nodeId: string, nextId: string) => {
    if (!manifest) return;
    if (!KEBAB_CASE.test(nextId) || manifest.nodes.some((node) => node.id === nextId)) {
      return; // invalid or duplicate — keep the current id
    }
    const renamed: FlowManifest = {
      ...manifest,
      nodes: manifest.nodes.map((node) => {
        const next =
          node.id === nodeId ? { ...node, id: nextId } : { ...node };
        if (next.onTimeout === nodeId) {
          next.onTimeout = nextId;
        }
        if (next.input !== undefined) {
          next.input = replaceNodeRefs(next.input, nodeId, nextId) as Record<string, unknown>;
        }
        if (typeof next.over === "string") {
          next.over = replaceNodeRefs(next.over, nodeId, nextId) as string;
        }
        return next;
      }),
      edges: manifest.edges.map((edge) => ({
        ...edge,
        from: edge.from === nodeId ? nextId : edge.from,
        to: edge.to === nodeId ? nextId : edge.to,
        when:
          edge.when !== undefined
            ? (replaceNodeRefs(edge.when, nodeId, nextId) as string)
            : undefined,
      })),
    };
    applyManifest(renamed);
    setPositions((prev) => {
      if (!(nodeId in prev)) return prev;
      const { [nodeId]: value, ...rest } = prev;
      return { ...rest, [nextId]: value };
    });
    setSelectedNodeId(nextId);
  };

  const deleteNode = (nodeId: string) => {
    if (!manifest) return;
    applyManifest({
      ...manifest,
      nodes: manifest.nodes.filter((node) => node.id !== nodeId),
      edges: manifest.edges.filter((edge) => edge.from !== nodeId && edge.to !== nodeId),
    });
    setPositions((prev) => omitPosition(prev, nodeId));
    setSelectedNodeId(null);
  };

  const addEdge = (edge: FlowEdge) => {
    if (!manifest) return;
    applyManifest({ ...manifest, edges: [...manifest.edges, edge] });
  };

  const updateEdge = (edgeIndex: number, patch: Partial<FlowEdge>) => {
    if (!manifest) return;
    applyManifest({
      ...manifest,
      edges: manifest.edges.map((edge, index) =>
        index === edgeIndex ? withPatch(edge, patch) : edge
      ),
    });
  };

  const deleteEdge = (edgeIndex: number) => {
    if (!manifest) return;
    applyManifest({
      ...manifest,
      edges: manifest.edges.filter((_, index) => index !== edgeIndex),
    });
  };

  const moveNode = (nodeId: string, position: CanvasPosition) => {
    setPositions((prev) => ({ ...prev, [nodeId]: position }));
  };

  const connectNodes = (fromId: string, toId: string) => {
    if (fromId === toId) return;
    addEdge({ from: fromId, to: toId });
  };

  /** Generates a unique kebab-case node id from a palette item's base id. */
  const nextNodeId = (base: string): string => {
    if (!manifest) return base;
    let candidate = base;
    let suffix = 2;
    while (manifest.nodes.some((node) => node.id === candidate)) {
      candidate = `${base}-${suffix}`;
      suffix += 1;
    }
    return candidate;
  };

  /**
   * Inserts a new node, connecting it from the currently selected node (if
   * any) — the palette's "connects from the selected node" interaction.
   */
  const insertNode = (node: FlowNode) => {
    if (!manifest) return;
    const fromId = selectedNodeId;
    applyManifest({
      ...manifest,
      nodes: [...manifest.nodes, node],
      edges: fromId ? [...manifest.edges, { from: fromId, to: node.id }] : manifest.edges,
    });
    selectNode(node.id);
  };

  const insertAgentItem = (item: AgentPaletteItem) => {
    if (!manifest) return;
    insertNode({ id: nextNodeId(item.id), type: "agent", ref: item.ref, label: item.label });
  };

  const insertControlItem = (item: ControlPaletteItem) => {
    if (!manifest) return;
    const previousOutput =
      item.supportsPreviousOutput && selectedNodeId
        ? { input: { previous: `{{ nodes.${selectedNodeId}.output }}` } }
        : {};
    insertNode({
      id: nextNodeId(item.id),
      type: item.nodeType,
      label: item.label,
      ...item.defaults,
      ...previousOutput,
    });
  };

  /** Starts a brand-new blank flow (palette's "Flows library" > New). */
  const startNewFlow = () => {
    applyManifest(createBlankFlow());
    setPositions({});
    setSelectedNodeId(null);
    toast({
      title: "New flow started",
      description: "Blank canvas ready — insert nodes from the palette.",
    });
  };

  /** Empties the current canvas without discarding the flow's identity. */
  const clearCanvas = () => {
    if (!manifest) return;
    applyManifest({ ...manifest, nodes: [], edges: [] });
    setPositions({});
    setSelectedNodeId(null);
    toast({ title: "Canvas cleared", description: "All nodes and edges were removed." });
  };

  /**
   * Save action: gates on local validation, re-checks against the E16 `/v2`
   * flows endpoint (non-mutating), then exports the canonical YAML.
   */
  const handleSave = async () => {
    if (!manifest) return;
    if (issueCount > 0) {
      toast({
        title: "Fix validation issues before saving",
        description: `${issueCount} issue${issueCount === 1 ? "" : "s"} found — see the Issues tab.`,
        variant: "destructive",
      });
      setActiveTab("issues");
      return;
    }
    setSaving(true);
    try {
      const result = await validateFlowV2(manifest);
      if (!result.valid) {
        toast({
          title: "Server validation failed",
          description: result.errors.join("; ") || "The manifest did not pass validation.",
          variant: "destructive",
        });
        return;
      }
      downloadFlowYaml(yamlText);
      toast({
        title: "flow.yaml exported",
        description: `${manifest.id}@${manifest.version} downloaded.`,
      });
    } catch (error) {
      toast({
        title: "Could not validate flow.yaml",
        description:
          error instanceof Error ? error.message : "Unexpected error contacting the control plane.",
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  const selectedNode =
    manifest?.nodes.find((node) => node.id === selectedNodeId) ?? null;

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-serif text-sm font-semibold text-ds-fg">
          {manifest ? `${manifest.id}@${manifest.version}` : "flow.yaml"}
        </h2>
        <Badge variant={issueCount === 0 ? "secondary" : "destructive"}>
          {issueCount === 0 ? "valid" : `${issueCount} issue${issueCount === 1 ? "" : "s"}`}
        </Badge>
        <div className="ml-auto flex items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={clearCanvas} disabled={!manifest}>
            Clear
          </Button>
          <Button type="button" size="sm" onClick={handleSave} disabled={!manifest || saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[240px_minmax(0,1fr)_360px]">
        <div className="min-h-[280px] lg:min-h-0">
          <FlowPalette
            catalog={catalog}
            catalogLoading={catalogLoading}
            catalogError={catalogError}
            selectedNodeId={selectedNodeId}
            onInsertAgent={insertAgentItem}
            onInsertControl={insertControlItem}
            onNewFlow={startNewFlow}
          />
        </div>

        <div className="min-h-[420px]">
          {manifest ? (
            <FlowCanvas
              manifest={manifest}
              selectedNodeId={selectedNodeId}
              errorNodeIds={errorNodeIds}
              onSelectNode={selectNode}
              positions={positions}
              onNodeMove={moveNode}
              onConnectNodes={connectNodes}
            />
          ) : (
            <div className="flex h-full items-center justify-center rounded-ds-lg border border-ds-line bg-ds-bg-2 p-6 text-sm text-ds-fg-2">
              The YAML document does not parse — fix it in the flow.yaml tab to
              render the canvas.
            </div>
          )}
        </div>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="min-h-0">
          <TabsList>
            <TabsTrigger value="inspector">Inspector</TabsTrigger>
            <TabsTrigger value="yaml">flow.yaml</TabsTrigger>
            <TabsTrigger value="issues">
              Issues{issueCount > 0 ? ` (${issueCount})` : ""}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="inspector">
            {manifest && selectedNode ? (
              <NodeInspector
                manifest={manifest}
                node={selectedNode}
                onUpdateNode={updateNode}
                onRenameNode={renameNode}
                onDeleteNode={deleteNode}
                onAddEdge={addEdge}
                onUpdateEdge={updateEdge}
                onDeleteEdge={deleteEdge}
              />
            ) : (
              <p className="rounded-ds-md border border-ds-line bg-ds-bg-2 px-3 py-2 text-sm text-ds-fg-2">
                Select a node on the canvas, or insert one from the palette, to
                edit its properties, guards, and human checkpoints.
              </p>
            )}
          </TabsContent>
          <TabsContent value="yaml">
            <div className="flex flex-col gap-2">
              <textarea
                aria-label="flow.yaml source"
                spellCheck={false}
                className={cn(
                  "h-[480px] w-full resize-y rounded-ds-md border border-ds-line bg-ds-bg px-3 py-2 font-mono text-xs text-ds-fg shadow-ds-sm",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent",
                  parseErrors.length > 0 && "border-ds-danger"
                )}
                value={yamlText}
                onChange={(event) => handleYamlChange(event.target.value)}
              />
              <p className="text-xs text-ds-fg-2">
                Edits sync to the canvas as soon as the document parses; visual
                edits rewrite this document in canonical form (deterministic
                round-trip).
              </p>
            </div>
          </TabsContent>
          <TabsContent value="issues">
            <ValidationPanel
              parseErrors={parseErrors}
              issues={issues}
              onSelectNode={selectNode}
            />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
