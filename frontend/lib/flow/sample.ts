/**
 * Default flow loaded by the editor — mirrors the worked example in
 * docs/v2_platform/templates/manifests/flow.yaml.example (feature delivery).
 */

import type { FlowManifest } from "./types";
import { serializeFlowYaml } from "./yaml";

export const SAMPLE_FLOW: FlowManifest = {
  schemaVersion: "1",
  id: "autodev/flow-feature-delivery",
  version: "1.0.0",
  name: "Feature Delivery",
  description: "Plan -> code -> apply patch -> validate -> human review -> evaluate.",
  hostApi: ">=2.0 <3.0",
  triggers: [
    { type: "message" },
    { type: "event", on: "flow.run.requested" },
  ],
  input: {
    schemaVersion: "1",
    type: "object",
    required: ["task", "repoRef"],
    properties: {
      task: { type: "string" },
      repoRef: { type: "string" },
    },
  },
  defaults: {
    retries: { maxAttempts: 3, backoff: "exponential", initialDelaySec: 2 },
    timeoutSec: 120,
  },
  nodes: [
    {
      id: "plan",
      type: "agent",
      ref: "autodev/agent-planner@>=1.0 <2.0",
      input: { task: "{{ flow.input.task }}" },
    },
    {
      id: "code",
      type: "agent",
      ref: "autodev/agent-coder@2.1.0",
      timeoutSec: 300,
      retries: { maxAttempts: 2, backoff: "exponential", initialDelaySec: 5 },
    },
    {
      id: "apply-and-validate",
      type: "skill",
      ref: "autodev/skill-apply-patch@>=1.0 <2.0",
      input: { patch: "{{ nodes.code.output.patch }}" },
    },
    { id: "quality-gate", type: "conditional" },
    {
      id: "human-review",
      type: "human",
      prompt: "Review the patch and Validation Gate results. Approve merge?",
      form: {
        schemaVersion: "1",
        type: "object",
        required: ["decision"],
        properties: {
          decision: { type: "string", enum: ["approve", "reject", "request-changes"] },
          notes: { type: "string" },
        },
      },
      timeoutSec: 86400,
      onTimeout: "escalate",
    },
    { id: "evaluate", type: "skill", ref: "autodev/skill-run-eval@>=1.0 <2.0" },
    { id: "escalate", type: "skill", ref: "autodev/skill-notify@>=1.0 <2.0" },
  ],
  edges: [
    { from: "plan", to: "code" },
    { from: "code", to: "apply-and-validate" },
    { from: "apply-and-validate", to: "quality-gate" },
    {
      from: "quality-gate",
      to: "human-review",
      when: "{{ nodes['apply-and-validate'].output.testsPassed == true }}",
    },
    {
      from: "quality-gate",
      to: "code",
      when: "{{ nodes['apply-and-validate'].output.testsPassed == false }}",
    },
    {
      from: "human-review",
      to: "evaluate",
      when: "{{ nodes['human-review'].output.decision == 'approve' }}",
    },
    {
      from: "human-review",
      to: "code",
      when: "{{ nodes['human-review'].output.decision == 'request-changes' }}",
    },
    { from: "human-review", to: "escalate", on: "timeout" },
  ],
  budgets: {
    maxCostUsd: 10.0,
    maxWallClockSec: 3600,
    maxTokens: 2000000,
  },
  output: {
    schemaVersion: "1",
    type: "object",
    properties: {
      merged: { type: "boolean" },
      evalScore: { type: "number" },
    },
  },
};

export const SAMPLE_FLOW_YAML: string = serializeFlowYaml(SAMPLE_FLOW);

/**
 * Build a fresh, empty flow manifest for the palette's "New" action
 * (Flows library section) — a minimal valid scaffold with no nodes/edges.
 *
 * @returns A new blank `FlowManifest`.
 */
export function createBlankFlow(): FlowManifest {
  return {
    schemaVersion: "1",
    id: "autodev/flow-untitled",
    version: "0.1.0",
    name: "Untitled flow",
    hostApi: ">=2.0 <3.0",
    nodes: [],
    edges: [],
  };
}
