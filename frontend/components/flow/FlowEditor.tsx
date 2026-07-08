"use client";

import * as React from "react";

import { FlowCanvas } from "@/components/flow/FlowCanvas";
import { NodeInspector } from "@/components/flow/NodeInspector";
import { ValidationPanel } from "@/components/flow/ValidationPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SAMPLE_FLOW_YAML } from "@/lib/flow/sample";
import {
  KEBAB_CASE,
  NODE_TYPES,
  type FlowEdge,
  type FlowManifest,
  type FlowNode,
  type NodeType,
} from "@/lib/flow/types";
import { validateFlow, type ValidationIssue } from "@/lib/flow/validate";
import { parseFlowYaml, serializeFlowYaml } from "@/lib/flow/yaml";
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

function defaultsForType(type: NodeType): Partial<FlowNode> {
  switch (type) {
    case "conditional":
      return {};
    case "human":
      return { prompt: "Describe the decision the operator must make." };
    case "map":
      return { ref: "namespace/skill-name", over: "{{ flow.input.items }}" };
    default:
      return { ref: "namespace/name" };
  }
}

/**
 * Visual flow editor (E10-S3): graph canvas + node inspector +
 * deterministic flow.yaml round-trip + real-time validation.
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
  const [newNodeType, setNewNodeType] = React.useState<NodeType>("agent");
  const [activeTab, setActiveTab] = React.useState("inspector");

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
    setSelectedNodeId(nextId);
  };

  const deleteNode = (nodeId: string) => {
    if (!manifest) return;
    applyManifest({
      ...manifest,
      nodes: manifest.nodes.filter((node) => node.id !== nodeId),
      edges: manifest.edges.filter((edge) => edge.from !== nodeId && edge.to !== nodeId),
    });
    setSelectedNodeId(null);
  };

  const addNode = () => {
    if (!manifest) return;
    let index = manifest.nodes.length + 1;
    let id = `${newNodeType}-${index}`;
    while (manifest.nodes.some((node) => node.id === id)) {
      index += 1;
      id = `${newNodeType}-${index}`;
    }
    const node: FlowNode = { id, type: newNodeType, ...defaultsForType(newNodeType) };
    applyManifest({ ...manifest, nodes: [...manifest.nodes, node] });
    selectNode(id);
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

  const selectedNode =
    manifest?.nodes.find((node) => node.id === selectedNodeId) ?? null;

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2">
          <Select
            value={newNodeType}
            onValueChange={(value) => setNewNodeType(value as NodeType)}
          >
            <SelectTrigger aria-label="New node type" className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {NODE_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button type="button" variant="secondary" size="sm" onClick={addNode} disabled={!manifest}>
            Add node
          </Button>
        </div>
        <div className="ml-auto flex items-center gap-2" aria-live="polite">
          {manifest ? (
            <span className="text-sm text-muted-foreground">
              {manifest.id}@{manifest.version}
            </span>
          ) : null}
          <Badge variant={issueCount === 0 ? "secondary" : "destructive"}>
            {issueCount === 0 ? "valid" : `${issueCount} issue${issueCount === 1 ? "" : "s"}`}
          </Badge>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-h-[420px]">
          {manifest ? (
            <FlowCanvas
              manifest={manifest}
              selectedNodeId={selectedNodeId}
              errorNodeIds={errorNodeIds}
              onSelectNode={selectNode}
            />
          ) : (
            <div className="flex h-full items-center justify-center rounded-lg border border-border bg-muted/30 p-6 text-sm text-muted-foreground">
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
              <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                Select a node on the canvas to edit its properties, guards, and
                human checkpoints.
              </p>
            )}
          </TabsContent>
          <TabsContent value="yaml">
            <div className="flex flex-col gap-2">
              <textarea
                aria-label="flow.yaml source"
                spellCheck={false}
                className={cn(
                  "h-[480px] w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-sm",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  parseErrors.length > 0 && "border-destructive"
                )}
                value={yamlText}
                onChange={(event) => handleYamlChange(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
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
