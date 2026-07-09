"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  NODE_TYPES,
  type FlowEdge,
  type FlowManifest,
  type FlowNode,
  type NodeType,
} from "@/lib/flow/types";
import { cn } from "@/lib/utils";

export type NodeInspectorProps = {
  manifest: FlowManifest;
  node: FlowNode;
  onUpdateNode: (nodeId: string, patch: Partial<FlowNode>) => void;
  onRenameNode: (nodeId: string, nextId: string) => void;
  onDeleteNode: (nodeId: string) => void;
  onAddEdge: (edge: FlowEdge) => void;
  onUpdateEdge: (edgeIndex: number, patch: Partial<FlowEdge>) => void;
  onDeleteEdge: (edgeIndex: number) => void;
};

const REF_NODE_TYPES: NodeType[] = ["agent", "skill", "tool", "subflow", "map"];

const NO_GUARD = "unguarded";

const fieldClass =
  "flex w-full rounded-ds-md border border-ds-line bg-ds-bg px-3 py-2 text-sm text-ds-fg shadow-ds-sm placeholder:text-ds-fg-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent";

function FieldLabel({ htmlFor, children }: { htmlFor: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="text-xs font-medium text-ds-fg-2">
      {children}
    </label>
  );
}

function decisionOptions(node: FlowNode): string[] {
  const form = node.form as
    | { properties?: { decision?: { enum?: unknown[] } } }
    | undefined;
  const options = form?.properties?.decision?.enum;
  if (Array.isArray(options) && options.length > 0) {
    return options.map(String);
  }
  return ["approve", "reject"];
}

/**
 * Human-in-the-loop preview (E10-S3-T3): renders the checkpoint exactly as an
 * operator would see it and shows which edge each decision would follow.
 */
function HumanPreview({
  node,
  outgoing,
}: {
  node: FlowNode;
  outgoing: Array<{ edge: FlowEdge; index: number }>;
}) {
  const [decision, setDecision] = React.useState<string | null>(null);
  const matched = decision
    ? outgoing.find(({ edge }) => edge.when?.includes(`'${decision}'`))
    : undefined;
  const timeoutEdge = outgoing.find(({ edge }) => edge.on === "timeout");

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Human checkpoint preview</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-ds-fg">{node.prompt ?? "(no prompt set)"}</p>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Simulate decision">
          {decisionOptions(node).map((option) => (
            <Button
              key={option}
              type="button"
              size="sm"
              variant={decision === option ? "default" : "outline"}
              onClick={() => setDecision(option)}
            >
              {option}
            </Button>
          ))}
        </div>
        <p className="text-xs text-ds-fg-2" aria-live="polite">
          {decision
            ? matched
              ? `Decision "${decision}" follows the edge to "${matched.edge.to}".`
              : `Decision "${decision}" matches no outgoing "when" guard.`
            : "Pick a decision to see which edge the run would follow."}
          {node.timeoutSec !== undefined
            ? ` On SLA expiry (${node.timeoutSec}s) the run follows ${
                timeoutEdge ? `the timeout edge to "${timeoutEdge.edge.to}"` : "no edge (missing on: timeout edge)"
              }.`
            : ""}
        </p>
      </CardContent>
    </Card>
  );
}

/** Property editor for the selected node and its outgoing edges (E10-S3-T2/T3). */
export function NodeInspector({
  manifest,
  node,
  onUpdateNode,
  onRenameNode,
  onDeleteNode,
  onAddEdge,
  onUpdateEdge,
  onDeleteEdge,
}: NodeInspectorProps) {
  const outgoing = manifest.edges
    .map((edge, index) => ({ edge, index }))
    .filter(({ edge }) => edge.from === node.id);
  const otherNodeIds = manifest.nodes.map((candidate) => candidate.id);
  const [newTarget, setNewTarget] = React.useState<string>("");

  const numberOrUndefined = (value: string): number | undefined =>
    value.trim() === "" ? undefined : Number(value);

  return (
    <div className="flex flex-col gap-4">
      <h4 className="font-serif text-sm font-semibold text-ds-fg">
        Editing node <span className="font-mono">{node.id}</span>
      </h4>

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="node-id">Node id (kebab-case)</FieldLabel>
        <Input
          id="node-id"
          key={node.id}
          defaultValue={node.id}
          onBlur={(event) => {
            const next = event.target.value.trim();
            if (next && next !== node.id) {
              onRenameNode(node.id, next);
            }
          }}
        />
      </div>

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="node-label">Label</FieldLabel>
        <Input
          id="node-label"
          key={`${node.id}-label`}
          defaultValue={node.label ?? ""}
          placeholder={node.id}
          onBlur={(event) =>
            onUpdateNode(node.id, { label: event.target.value.trim() || undefined })
          }
        />
      </div>

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="node-type">Type</FieldLabel>
        <Select
          value={node.type}
          onValueChange={(value) => onUpdateNode(node.id, { type: value as NodeType })}
        >
          <SelectTrigger id="node-type" aria-label="Node type">
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
      </div>

      {REF_NODE_TYPES.includes(node.type) ? (
        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="node-ref">Ref (namespace/name[@version])</FieldLabel>
          <Input
            id="node-ref"
            value={node.ref ?? ""}
            placeholder="autodev/agent-coder@2.1.0"
            onChange={(event) =>
              onUpdateNode(node.id, { ref: event.target.value || undefined })
            }
          />
        </div>
      ) : null}

      {node.type === "agent" ? (
        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="node-model">Model override</FieldLabel>
          <Input
            id="node-model"
            value={node.model ?? ""}
            placeholder="claude-sonnet-5"
            onChange={(event) =>
              onUpdateNode(node.id, { model: event.target.value || undefined })
            }
          />
        </div>
      ) : null}

      {node.type === "human" ? (
        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="node-prompt">Prompt shown to the human</FieldLabel>
          <textarea
            id="node-prompt"
            className={cn(fieldClass, "min-h-[72px] resize-y")}
            value={node.prompt ?? ""}
            onChange={(event) =>
              onUpdateNode(node.id, { prompt: event.target.value || undefined })
            }
          />
        </div>
      ) : null}

      {node.type === "map" ? (
        <>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="node-over">Over (collection expression)</FieldLabel>
            <Input
              id="node-over"
              value={node.over ?? ""}
              placeholder="{{ nodes.plan.output.items }}"
              onChange={(event) =>
                onUpdateNode(node.id, { over: event.target.value || undefined })
              }
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="node-max-parallel">Max parallel</FieldLabel>
            <Input
              id="node-max-parallel"
              type="number"
              min={1}
              value={node.maxParallel ?? ""}
              onChange={(event) =>
                onUpdateNode(node.id, { maxParallel: numberOrUndefined(event.target.value) })
              }
            />
          </div>
        </>
      ) : null}

      {node.type !== "conditional" ? (
        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="node-timeout">Timeout (seconds)</FieldLabel>
          <Input
            id="node-timeout"
            type="number"
            min={1}
            value={node.timeoutSec ?? ""}
            onChange={(event) =>
              onUpdateNode(node.id, { timeoutSec: numberOrUndefined(event.target.value) })
            }
          />
        </div>
      ) : null}

      {node.type === "human" ? (
        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="node-on-timeout">On timeout, go to</FieldLabel>
          <Select
            value={node.onTimeout ?? "none"}
            onValueChange={(value) =>
              onUpdateNode(node.id, { onTimeout: value === "none" ? undefined : value })
            }
          >
            <SelectTrigger id="node-on-timeout" aria-label="Timeout target node">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">(none)</SelectItem>
              {otherNodeIds
                .filter((id) => id !== node.id)
                .map((id) => (
                  <SelectItem key={id} value={id}>
                    {id}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}

      {node.type === "human" ? <HumanPreview node={node} outgoing={outgoing} /> : null}

      <div className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-ds-fg-2">
          Outgoing edges <Badge variant="secondary">{outgoing.length}</Badge>
        </h3>
        {outgoing.map(({ edge, index }) => {
          const guardMode = edge.on !== undefined ? "on" : edge.when !== undefined ? "when" : NO_GUARD;
          return (
            <div
              key={index}
              className="flex flex-col gap-2 rounded-ds-md border border-ds-line p-2"
            >
              <div className="flex items-center gap-2">
                <Select
                  value={edge.to}
                  onValueChange={(value) => onUpdateEdge(index, { to: value })}
                >
                  <SelectTrigger aria-label={`Edge ${index + 1} target`} className="flex-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {otherNodeIds.map((id) => (
                      <SelectItem key={id} value={id}>
                        {id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={`Remove edge to ${edge.to}`}
                  onClick={() => onDeleteEdge(index)}
                >
                  Remove
                </Button>
              </div>
              <Select
                value={guardMode}
                onValueChange={(value) => {
                  if (value === NO_GUARD) {
                    onUpdateEdge(index, { when: undefined, on: undefined });
                  } else if (value === "when") {
                    onUpdateEdge(index, { when: edge.when ?? "{{  }}", on: undefined });
                  } else {
                    onUpdateEdge(index, { when: undefined, on: "timeout" });
                  }
                }}
              >
                <SelectTrigger aria-label={`Edge ${index + 1} guard type`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_GUARD}>unguarded</SelectItem>
                  <SelectItem value="when">when (predicate)</SelectItem>
                  <SelectItem value="on">on: timeout (human SLA)</SelectItem>
                </SelectContent>
              </Select>
              {guardMode === "when" ? (
                <Input
                  aria-label={`Edge ${index + 1} predicate`}
                  className="font-mono"
                  value={edge.when ?? ""}
                  placeholder="{{ nodes.gate.output.ok == true }}"
                  onChange={(event) => onUpdateEdge(index, { when: event.target.value })}
                />
              ) : null}
            </div>
          );
        })}
        <div className="flex items-center gap-2">
          <Select value={newTarget} onValueChange={setNewTarget}>
            <SelectTrigger aria-label="New edge target" className="flex-1">
              <SelectValue placeholder="Add edge to…" />
            </SelectTrigger>
            <SelectContent>
              {otherNodeIds.map((id) => (
                <SelectItem key={id} value={id}>
                  {id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={newTarget === ""}
            onClick={() => {
              if (newTarget) {
                onAddEdge({ from: node.id, to: newTarget });
                setNewTarget("");
              }
            }}
          >
            Add edge
          </Button>
        </div>
      </div>

      <Button
        type="button"
        variant="destructive"
        size="sm"
        onClick={() => onDeleteNode(node.id)}
      >
        Delete node
      </Button>
    </div>
  );
}
