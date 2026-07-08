import { describe, expect, it } from "vitest";

import { CANVAS_PADDING, H_GAP, NODE_WIDTH, layoutFlow } from "./layout";
import { SAMPLE_FLOW } from "./sample";
import type { FlowManifest } from "./types";

describe("layoutFlow", () => {
  it("is deterministic for the same manifest", () => {
    expect(layoutFlow(SAMPLE_FLOW)).toEqual(layoutFlow(SAMPLE_FLOW));
  });

  it("assigns increasing layers along the main path", () => {
    const { positions } = layoutFlow(SAMPLE_FLOW);
    const layerX = (id: string) => positions[id].x;
    expect(layerX("plan")).toBeLessThan(layerX("code"));
    expect(layerX("code")).toBeLessThan(layerX("apply-and-validate"));
    expect(layerX("apply-and-validate")).toBeLessThan(layerX("quality-gate"));
    expect(layerX("quality-gate")).toBeLessThan(layerX("human-review"));
    expect(layerX("human-review")).toBeLessThan(layerX("evaluate"));
    // sibling targets of human-review share its next layer
    expect(layerX("evaluate")).toBe(layerX("escalate"));
  });

  it("separates nodes that share a layer vertically", () => {
    const { positions } = layoutFlow(SAMPLE_FLOW);
    expect(positions.evaluate.x).toBe(positions.escalate.x);
    expect(positions.evaluate.y).not.toBe(positions.escalate.y);
  });

  it("places the entry node at the first layer", () => {
    const { positions } = layoutFlow(SAMPLE_FLOW);
    expect(positions.plan.x).toBe(CANVAS_PADDING);
    expect(positions.code.x).toBe(CANVAS_PADDING + NODE_WIDTH + H_GAP);
  });

  it("handles empty and disconnected graphs without crashing", () => {
    const empty: FlowManifest = {
      schemaVersion: "1",
      id: "ns/flow",
      version: "1.0.0",
      hostApi: ">=2.0 <3.0",
      nodes: [],
      edges: [],
    };
    expect(layoutFlow(empty).positions).toEqual({});

    const disconnected: FlowManifest = {
      ...empty,
      nodes: [
        { id: "a", type: "tool", ref: "ns/tool-a" },
        { id: "b", type: "tool", ref: "ns/tool-b" },
      ],
      edges: [],
    };
    const { positions } = layoutFlow(disconnected);
    expect(positions.a).toBeDefined();
    expect(positions.b).toBeDefined();
    expect(positions.a).not.toEqual(positions.b);
  });
});
