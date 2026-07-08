/**
 * Client-side flow graph validation (E10-S3-T3) mirroring the rules that
 * `backend/flows/graph.py` + `backend/flows/manifest.py` enforce
 * (docs/flows/spec.md § "Graph validity rules"). Every error is reported —
 * never just the first one.
 */

import {
  FLOW_ID_PATTERN,
  KEBAB_CASE,
  NODE_TYPES,
  REF_PATTERN,
  SEMVER_PATTERN,
  TRIGGER_TYPES,
  isGuarded,
  type FlowEdge,
  type FlowManifest,
  type FlowNode,
  type NodeType,
  type RetryPolicy,
} from "./types";

export type ValidationIssue = {
  code: string;
  message: string;
  /** Node the issue is anchored to, when applicable. */
  nodeId?: string;
  /** Index into `manifest.edges`, when applicable. */
  edgeIndex?: number;
};

const REF_NODE_TYPES: NodeType[] = ["agent", "skill", "tool", "subflow", "map"];

function issue(
  code: string,
  message: string,
  anchor: { nodeId?: string; edgeIndex?: number } = {}
): ValidationIssue {
  return { code, message, ...anchor };
}

function edgeLabel(edge: FlowEdge, index: number): string {
  return `edge #${index + 1} (${edge.from} -> ${edge.to})`;
}

function validateTopLevel(manifest: FlowManifest, issues: ValidationIssue[]): void {
  if (manifest.schemaVersion !== "1") {
    issues.push(
      issue("schema-version", `schemaVersion must be "1" (got "${manifest.schemaVersion}")`)
    );
  }
  if (!FLOW_ID_PATTERN.test(manifest.id)) {
    issues.push(
      issue("flow-id", `flow id "${manifest.id}" must be "namespace/name" in kebab-case`)
    );
  }
  if (!SEMVER_PATTERN.test(manifest.version)) {
    issues.push(
      issue("flow-version", `flow version "${manifest.version}" must be SemVer MAJOR.MINOR.PATCH`)
    );
  }
  if (typeof manifest.hostApi !== "string" || manifest.hostApi.trim() === "") {
    issues.push(issue("host-api", "hostApi must be a non-empty compatibility range"));
  }
  for (const trigger of manifest.triggers ?? []) {
    if (!TRIGGER_TYPES.includes(trigger.type)) {
      issues.push(issue("trigger-type", `unknown trigger type "${trigger.type}"`));
      continue;
    }
    if (trigger.type === "cron" && !trigger.schedule) {
      issues.push(issue("trigger-cron", 'cron trigger requires a "schedule"'));
    }
    if (trigger.type === "event" && !trigger.on) {
      issues.push(issue("trigger-event", 'event trigger requires an "on" event name'));
    }
  }
}

function validateRetries(
  retries: RetryPolicy,
  where: string,
  anchor: { nodeId?: string },
  issues: ValidationIssue[]
): void {
  if (retries.maxAttempts !== undefined && (!Number.isInteger(retries.maxAttempts) || retries.maxAttempts < 1)) {
    issues.push(issue("retries", `${where}: retries.maxAttempts must be an integer >= 1`, anchor));
  }
  if (retries.backoff !== undefined && retries.backoff !== "fixed" && retries.backoff !== "exponential") {
    issues.push(issue("retries", `${where}: retries.backoff must be "fixed" or "exponential"`, anchor));
  }
  if (retries.initialDelaySec !== undefined && (typeof retries.initialDelaySec !== "number" || retries.initialDelaySec < 0)) {
    issues.push(issue("retries", `${where}: retries.initialDelaySec must be >= 0`, anchor));
  }
}

function validateNodeFields(node: FlowNode, issues: ValidationIssue[]): void {
  const anchor = { nodeId: node.id };
  if (!NODE_TYPES.includes(node.type)) {
    issues.push(issue("node-type", `node "${node.id}" has unknown type "${node.type}"`, anchor));
    return;
  }
  if (REF_NODE_TYPES.includes(node.type)) {
    if (!node.ref) {
      issues.push(issue("node-ref", `${node.type} node "${node.id}" requires a "ref"`, anchor));
    } else if (!REF_PATTERN.test(node.ref)) {
      issues.push(
        issue(
          "node-ref",
          `node "${node.id}": ref "${node.ref}" must be "namespace/name[@version-or-range]"`,
          anchor
        )
      );
    }
  }
  if (node.type === "conditional") {
    if (node.ref !== undefined || node.input !== undefined) {
      issues.push(
        issue(
          "conditional-fields",
          `conditional node "${node.id}" must not declare "ref" or "input"`,
          anchor
        )
      );
    }
  }
  if (node.type === "human" && !node.prompt) {
    issues.push(issue("human-prompt", `human node "${node.id}" requires a "prompt"`, anchor));
  }
  if (node.type !== "human" && node.onTimeout !== undefined) {
    issues.push(
      issue("on-timeout", `"onTimeout" is only legal on human nodes (node "${node.id}")`, anchor)
    );
  }
  if (node.type === "map" && !node.over) {
    issues.push(issue("map-over", `map node "${node.id}" requires an "over" expression`, anchor));
  }
  if (node.timeoutSec !== undefined && (typeof node.timeoutSec !== "number" || node.timeoutSec <= 0)) {
    issues.push(issue("timeout", `node "${node.id}": timeoutSec must be a positive number`, anchor));
  }
  if (node.retries) {
    validateRetries(node.retries, `node "${node.id}"`, anchor, issues);
  }
}

/**
 * Lightweight expression check: every `nodes.<id>` / `nodes['<id>']` path
 * must reference a declared node (and only its `output`), `flow.<root>` must
 * be `flow.input`, and `item` is legal only inside map-node bindings.
 */
function validateExpression(
  expression: string,
  context: { where: string; nodeIds: Set<string>; allowItem: boolean; nodeId?: string; edgeIndex?: number },
  issues: ValidationIssue[]
): void {
  const anchor = { nodeId: context.nodeId, edgeIndex: context.edgeIndex };
  const nodePaths = [
    ...Array.from(expression.matchAll(/\bnodes\.([A-Za-z0-9_-]+)(\.[A-Za-z0-9_]+)?/g)),
    ...Array.from(expression.matchAll(/\bnodes\['([^']+)'\](\.[A-Za-z0-9_]+)?/g)),
  ];
  for (const match of nodePaths) {
    const [, nodeId, segment] = match;
    if (!context.nodeIds.has(nodeId)) {
      issues.push(
        issue("expr-unknown-node", `${context.where}: references unknown node "${nodeId}"`, anchor)
      );
    }
    if (segment !== undefined && segment !== ".output") {
      issues.push(
        issue(
          "expr-node-output",
          `${context.where}: only "nodes.${nodeId}.output" is addressable (got "nodes.${nodeId}${segment}")`,
          anchor
        )
      );
    }
  }
  for (const match of Array.from(expression.matchAll(/\bflow\.([A-Za-z0-9_]+)/g))) {
    if (match[1] !== "input") {
      issues.push(
        issue("expr-flow-root", `${context.where}: unknown state root "flow.${match[1]}"`, anchor)
      );
    }
  }
  if (!context.allowItem && /\bitem\b/.test(expression)) {
    issues.push(
      issue(
        "expr-item-scope",
        `${context.where}: "item" is only available inside map-node bindings`,
        anchor
      )
    );
  }
}

function collectTemplates(value: unknown, out: string[]): void {
  if (typeof value === "string") {
    for (const match of Array.from(value.matchAll(/\{\{([\s\S]*?)\}\}/g))) {
      out.push(match[1]);
    }
  } else if (Array.isArray(value)) {
    value.forEach((entry) => collectTemplates(entry, out));
  } else if (typeof value === "object" && value !== null) {
    Object.values(value).forEach((entry) => collectTemplates(entry, out));
  }
}

function validateGraph(manifest: FlowManifest, issues: ValidationIssue[]): void {
  const nodes = manifest.nodes;
  const edges = manifest.edges;
  const nodeIds = new Set<string>();

  for (const node of nodes) {
    if (nodeIds.has(node.id)) {
      issues.push(issue("duplicate-id", `duplicate node id "${node.id}"`, { nodeId: node.id }));
    }
    nodeIds.add(node.id);
    if (!KEBAB_CASE.test(node.id)) {
      issues.push(
        issue("node-id", `node id "${node.id}" must be kebab-case`, { nodeId: node.id })
      );
    }
  }

  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const incoming = new Map<string, number>();
  const outgoing = new Map<string, FlowEdge[]>();

  edges.forEach((edge, index) => {
    for (const endpoint of [edge.from, edge.to]) {
      if (!nodeIds.has(endpoint)) {
        issues.push(
          issue(
            "edge-endpoint",
            `${edgeLabel(edge, index)}: unknown node "${endpoint}"`,
            { edgeIndex: index }
          )
        );
      }
    }
    if (edge.when !== undefined && edge.on !== undefined) {
      issues.push(
        issue(
          "edge-guard",
          `${edgeLabel(edge, index)}: "when" and "on" are mutually exclusive`,
          { edgeIndex: index }
        )
      );
    }
    if (edge.on !== undefined) {
      if (edge.on !== "timeout") {
        issues.push(
          issue("edge-signal", `${edgeLabel(edge, index)}: unknown signal "${edge.on}"`, {
            edgeIndex: index,
          })
        );
      } else {
        const source = nodeById.get(edge.from);
        if (source && source.type !== "human") {
          issues.push(
            issue(
              "timeout-source",
              `${edgeLabel(edge, index)}: "on: timeout" is only legal leaving human nodes`,
              { edgeIndex: index }
            )
          );
        }
        if (source && source.type === "human") {
          if (source.timeoutSec === undefined) {
            issues.push(
              issue(
                "timeout-missing",
                `human node "${source.id}" needs "timeoutSec" for its timeout edge`,
                { nodeId: source.id }
              )
            );
          }
          if (source.onTimeout !== undefined && source.onTimeout !== edge.to) {
            issues.push(
              issue(
                "timeout-target",
                `human node "${source.id}": onTimeout ("${source.onTimeout}") must match the timeout edge target ("${edge.to}")`,
                { nodeId: source.id }
              )
            );
          }
        }
      }
    }
    incoming.set(edge.to, (incoming.get(edge.to) ?? 0) + 1);
    outgoing.set(edge.from, [...(outgoing.get(edge.from) ?? []), edge]);
  });

  // onTimeout declared but no matching timeout edge.
  for (const node of nodes) {
    if (node.type === "human" && node.onTimeout !== undefined) {
      const hasTimeoutEdge = (outgoing.get(node.id) ?? []).some((edge) => edge.on === "timeout");
      if (!hasTimeoutEdge) {
        issues.push(
          issue(
            "timeout-edge-missing",
            `human node "${node.id}" declares onTimeout but has no "on: timeout" edge`,
            { nodeId: node.id }
          )
        );
      }
    }
  }

  // Entry / terminal nodes.
  const entries = nodes.filter((node) => !incoming.has(node.id));
  if (nodes.length > 0 && entries.length !== 1) {
    issues.push(
      issue(
        "entry-node",
        `flow must have exactly one entry node (found ${entries.length}: ${entries
          .map((node) => node.id)
          .join(", ") || "none"})`
      )
    );
  }
  const terminals = nodes.filter((node) => (outgoing.get(node.id) ?? []).length === 0);
  if (nodes.length > 0 && terminals.length === 0) {
    issues.push(issue("terminal-node", "flow must have at least one terminal node"));
  }

  // Reachability from the entry node.
  if (entries.length === 1) {
    const reachable = new Set<string>([entries[0].id]);
    const queue = [entries[0].id];
    while (queue.length > 0) {
      const current = queue.shift() as string;
      for (const edge of outgoing.get(current) ?? []) {
        if (nodeIds.has(edge.to) && !reachable.has(edge.to)) {
          reachable.add(edge.to);
          queue.push(edge.to);
        }
      }
    }
    for (const node of nodes) {
      if (!reachable.has(node.id)) {
        issues.push(
          issue("unreachable", `node "${node.id}" is not reachable from the entry node`, {
            nodeId: node.id,
          })
        );
      }
    }
  }

  // No unconditional cycles: the subgraph of unguarded edges must be acyclic.
  const unguardedAdj = new Map<string, string[]>();
  for (const edge of edges) {
    if (!isGuarded(edge) && nodeIds.has(edge.from) && nodeIds.has(edge.to)) {
      unguardedAdj.set(edge.from, [...(unguardedAdj.get(edge.from) ?? []), edge.to]);
    }
  }
  const state = new Map<string, "visiting" | "done">();
  const cycleNodes = new Set<string>();
  const visit = (id: string, stack: string[]): void => {
    state.set(id, "visiting");
    stack.push(id);
    for (const next of unguardedAdj.get(id) ?? []) {
      if (state.get(next) === "visiting") {
        stack.slice(stack.indexOf(next)).forEach((member) => cycleNodes.add(member));
      } else if (!state.has(next)) {
        visit(next, stack);
      }
    }
    stack.pop();
    state.set(id, "done");
  };
  for (const node of nodes) {
    if (!state.has(node.id)) {
      visit(node.id, []);
    }
  }
  if (cycleNodes.size > 0) {
    issues.push(
      issue(
        "unconditional-cycle",
        `unconditional cycle detected through: ${Array.from(cycleNodes).sort().join(", ")} — at least one edge in a cycle must be guarded`
      )
    );
  }

  // Fan-out rules.
  for (const node of nodes) {
    const out = outgoing.get(node.id) ?? [];
    if (node.type === "conditional") {
      if (out.length < 2) {
        issues.push(
          issue(
            "conditional-fanout",
            `conditional node "${node.id}" needs at least two outgoing edges (has ${out.length})`,
            { nodeId: node.id }
          )
        );
      }
      if (out.some((edge) => !isGuarded(edge))) {
        issues.push(
          issue(
            "conditional-guards",
            `every edge leaving conditional node "${node.id}" must be guarded`,
            { nodeId: node.id }
          )
        );
      }
    } else if (out.filter((edge) => !isGuarded(edge)).length > 1) {
      issues.push(
        issue(
          "implicit-fanout",
          `node "${node.id}" has more than one unguarded outgoing edge (no implicit parallel fan-out; use a map node)`,
          { nodeId: node.id }
        )
      );
    }
  }
}

function validateExpressions(manifest: FlowManifest, issues: ValidationIssue[]): void {
  const nodeIds = new Set(manifest.nodes.map((node) => node.id));

  manifest.edges.forEach((edge, index) => {
    if (edge.when !== undefined) {
      validateExpression(
        edge.when,
        {
          where: `${edgeLabel(edge, index)} "when"`,
          nodeIds,
          allowItem: false,
          edgeIndex: index,
        },
        issues
      );
    }
  });

  for (const node of manifest.nodes) {
    const templates: string[] = [];
    collectTemplates(node.input, templates);
    for (const template of templates) {
      validateExpression(
        template,
        {
          where: `node "${node.id}" input binding`,
          nodeIds,
          allowItem: node.type === "map",
          nodeId: node.id,
        },
        issues
      );
    }
    if (node.type === "map" && node.over) {
      const overTemplates: string[] = [];
      collectTemplates(node.over, overTemplates);
      for (const template of overTemplates.length > 0 ? overTemplates : [node.over]) {
        validateExpression(
          template,
          { where: `map node "${node.id}" "over"`, nodeIds, allowItem: false, nodeId: node.id },
          issues
        );
      }
    }
  }
}

/** Validate a manifest; returns every issue found (empty array = valid). */
export function validateFlow(manifest: FlowManifest): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  validateTopLevel(manifest, issues);
  if (manifest.defaults?.retries) {
    validateRetries(manifest.defaults.retries, "defaults", {}, issues);
  }
  for (const node of manifest.nodes) {
    validateNodeFields(node, issues);
  }
  validateGraph(manifest, issues);
  validateExpressions(manifest, issues);
  return issues;
}
