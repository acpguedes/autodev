/**
 * Static content for the Flow builder palette (E17-S6): the eight built-in
 * agent types and the flow-control blocks from the "Execution Control
 * Center" redesign prototype (layout_prototype_brainstorm §5.4).
 *
 * These are editor-only conveniences — clicking an entry seeds a
 * `FlowNode` with sensible defaults, which the operator can still edit
 * freely (including the `ref`) via the NodeInspector. They do not claim to
 * match any particular backend agent registry.
 */

import type { FlowNode, NodeType } from "./types";

/** A palette entry that inserts an `agent` node for one of the 8 built-in agent types. */
export type AgentPaletteItem = {
  kind: "agent";
  id: string;
  label: string;
  description: string;
  /** Placeholder ref; editable afterwards via the inspector. */
  ref: string;
};

/** A palette entry that inserts a flow-control block (conditional, loop, human, etc.). */
export type ControlPaletteItem = {
  kind: "control";
  id: string;
  label: string;
  description: string;
  nodeType: NodeType;
  /** Defaults merged onto the new node (besides `id`/`type`/`label`). */
  defaults: Partial<FlowNode>;
  /**
   * When true and a node is currently selected at insertion time, the new
   * node's `input.previous` is populated with a `{{ nodes.<selected>.output }}`
   * template ("include previous step output").
   */
  supportsPreviousOutput?: boolean;
};

export type PaletteItem = AgentPaletteItem | ControlPaletteItem;

/** The eight built-in agent types shown in the palette's "Agents" section. */
export const AGENT_PALETTE_ITEMS: AgentPaletteItem[] = [
  {
    kind: "agent",
    id: "planner",
    label: "Planner",
    description: "Breaks a goal down into an ordered plan of steps.",
    ref: "autodev/agent-planner",
  },
  {
    kind: "agent",
    id: "navigator",
    label: "Navigator",
    description: "Explores the codebase and locates relevant context.",
    ref: "autodev/agent-navigator",
  },
  {
    kind: "agent",
    id: "analyzer",
    label: "Analyzer",
    description: "Analyzes code, logs, or data to surface findings.",
    ref: "autodev/agent-analyzer",
  },
  {
    kind: "agent",
    id: "coder",
    label: "Coder",
    description: "Writes or edits code and produces a patch.",
    ref: "autodev/agent-coder",
  },
  {
    kind: "agent",
    id: "validator",
    label: "Validator",
    description: "Runs checks (tests, lint, build) against a change.",
    ref: "autodev/agent-validator",
  },
  {
    kind: "agent",
    id: "reviewer",
    label: "Reviewer",
    description: "Reviews a patch for correctness and quality.",
    ref: "autodev/agent-reviewer",
  },
  {
    kind: "agent",
    id: "docs",
    label: "Docs",
    description: "Drafts or updates documentation for a change.",
    ref: "autodev/agent-docs",
  },
  {
    kind: "agent",
    id: "security",
    label: "Security",
    description: "Audits a change for security concerns.",
    ref: "autodev/agent-security",
  },
];

/** Flow-control blocks shown in the palette's "Flow control" section. */
export const CONTROL_PALETTE_ITEMS: ControlPaletteItem[] = [
  {
    kind: "control",
    id: "conditional",
    label: "Conditional",
    description: "Branches the run based on a yes/no predicate.",
    nodeType: "conditional",
    defaults: {},
  },
  {
    kind: "control",
    id: "loop",
    label: "Loop",
    description: "Repeats over a collection until a condition or a max iteration count.",
    nodeType: "map",
    defaults: { ref: "namespace/skill-name", over: "{{ flow.input.items }}", maxParallel: 1 },
  },
  {
    kind: "control",
    id: "human-approval",
    label: "Human approval",
    description: "Pauses the run for a human decision before continuing.",
    nodeType: "human",
    defaults: { prompt: "Review and approve to continue." },
  },
  {
    kind: "control",
    id: "parallel",
    label: "Parallel (join)",
    description: "Runs branches concurrently and joins the results.",
    nodeType: "map",
    defaults: { ref: "namespace/skill-name", over: "{{ flow.input.items }}", maxParallel: 4 },
  },
  {
    kind: "control",
    id: "prompt-step",
    label: "Prompt/Step",
    description: "A single agent step; can include the previous step's output.",
    nodeType: "agent",
    defaults: { ref: "namespace/name" },
    supportsPreviousOutput: true,
  },
  {
    kind: "control",
    id: "start",
    label: "Start",
    description: "Marks the entry point of the flow.",
    nodeType: "agent",
    defaults: { ref: "namespace/name" },
  },
  {
    kind: "control",
    id: "end",
    label: "End",
    description: "Marks a terminal point of the flow.",
    nodeType: "agent",
    defaults: { ref: "namespace/name" },
  },
];
