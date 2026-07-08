/**
 * TypeScript mirror of the `flow.yaml` manifest contract (schemaVersion "1").
 *
 * Canonical spec: docs/flows/spec.md (E3-S1) and
 * backend/flows/schemas/flow.schema.json. Field vocabulary and validation
 * rules implemented here must stay aligned with `backend/flows`.
 */

export const NODE_TYPES = [
  "agent",
  "skill",
  "tool",
  "conditional",
  "human",
  "subflow",
  "map",
] as const;

export type NodeType = (typeof NODE_TYPES)[number];

export const TRIGGER_TYPES = ["message", "webhook", "cron", "event"] as const;

export type TriggerType = (typeof TRIGGER_TYPES)[number];

export type RetryPolicy = {
  maxAttempts?: number;
  backoff?: "fixed" | "exponential";
  initialDelaySec?: number;
};

export type FlowTrigger = {
  type: TriggerType;
  /** Required when type === "cron". */
  schedule?: string;
  /** Required when type === "event". */
  on?: string;
  [extra: string]: unknown;
};

export type FlowDefaults = {
  retries?: RetryPolicy;
  timeoutSec?: number;
};

export type FlowBudgets = {
  maxCostUsd?: number;
  maxWallClockSec?: number;
  maxTokens?: number;
};

export type FlowNode = {
  id: string;
  type: NodeType;
  /** Required for agent | skill | tool | subflow | map. */
  ref?: string;
  /** Input bindings ({{ ... }} templates over flow state). */
  input?: Record<string, unknown>;
  timeoutSec?: number;
  retries?: RetryPolicy;
  /** human nodes. */
  prompt?: string;
  form?: Record<string, unknown>;
  onTimeout?: string;
  /** map nodes. */
  over?: string;
  reduce?: string;
  maxParallel?: number;
  [extra: string]: unknown;
};

export type FlowEdge = {
  from: string;
  to: string;
  /** Predicate guard — mutually exclusive with `on`. */
  when?: string;
  /** Signal guard (only "timeout", leaving human nodes). */
  on?: string;
  [extra: string]: unknown;
};

export type FlowManifest = {
  schemaVersion: string;
  id: string;
  version: string;
  hostApi: string;
  name?: string;
  description?: string;
  triggers?: FlowTrigger[];
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  defaults?: FlowDefaults;
  nodes: FlowNode[];
  edges: FlowEdge[];
  budgets?: FlowBudgets;
  [extra: string]: unknown;
};

/** An edge is guarded when it declares `when` or `on`. */
export function isGuarded(edge: FlowEdge): boolean {
  return edge.when !== undefined || edge.on !== undefined;
}

export const KEBAB_CASE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

/** `namespace/name[@version-or-range]` */
export const REF_PATTERN =
  /^[a-z0-9]+(-[a-z0-9]+)*\/[a-z0-9]+(-[a-z0-9]+)*(@.+)?$/;

export const FLOW_ID_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*\/[a-z0-9]+(-[a-z0-9]+)*$/;

export const SEMVER_PATTERN = /^\d+\.\d+\.\d+$/;
