import { describe, expect, it } from "vitest";

import { SAMPLE_FLOW } from "./sample";
import type { FlowEdge, FlowManifest, FlowNode } from "./types";
import { validateFlow } from "./validate";

function makeFlow(nodes: FlowNode[], edges: FlowEdge[], overrides: Partial<FlowManifest> = {}): FlowManifest {
  return {
    schemaVersion: "1",
    id: "ns/flow",
    version: "1.0.0",
    hostApi: ">=2.0 <3.0",
    nodes,
    edges,
    ...overrides,
  };
}

const tool = (id: string): FlowNode => ({ id, type: "tool", ref: `ns/tool-${id}` });

function codes(manifest: FlowManifest): string[] {
  return validateFlow(manifest).map((issue) => issue.code);
}

describe("validateFlow", () => {
  it("accepts the sample feature-delivery flow", () => {
    expect(validateFlow(SAMPLE_FLOW)).toEqual([]);
  });

  it("rejects bad top-level metadata", () => {
    const flow = makeFlow([tool("a")], [], {
      schemaVersion: "2",
      id: "NotKebab",
      version: "1.0",
      hostApi: " ",
    });
    const found = codes(flow);
    expect(found).toEqual(
      expect.arrayContaining(["schema-version", "flow-id", "flow-version", "host-api"])
    );
  });

  it("requires trigger-specific fields", () => {
    const flow = makeFlow([tool("a")], [], {
      triggers: [{ type: "cron" }, { type: "event" }],
    });
    expect(codes(flow)).toEqual(expect.arrayContaining(["trigger-cron", "trigger-event"]));
  });

  it("enforces kebab-case, unique node ids", () => {
    const flow = makeFlow(
      [tool("Bad_Id"), tool("dup"), tool("dup")],
      [
        { from: "Bad_Id", to: "dup" },
      ]
    );
    expect(codes(flow)).toEqual(expect.arrayContaining(["node-id", "duplicate-id"]));
  });

  it("requires ref on agent/skill/tool/subflow/map and prompt on human", () => {
    const flow = makeFlow(
      [
        { id: "a", type: "agent" },
        { id: "b", type: "human", timeoutSec: 10 },
        { id: "c", type: "map", ref: "ns/skill-x" },
      ],
      [
        { from: "a", to: "b" },
        { from: "b", to: "c" },
      ]
    );
    expect(codes(flow)).toEqual(
      expect.arrayContaining(["node-ref", "human-prompt", "map-over"])
    );
  });

  it("rejects ref/input on conditional nodes and enforces guarded fan-out", () => {
    const flow = makeFlow(
      [
        tool("a"),
        { id: "gate", type: "conditional", ref: "ns/x" },
        tool("b"),
        tool("c"),
      ],
      [
        { from: "a", to: "gate" },
        { from: "gate", to: "b" }, // unguarded conditional edge
        { from: "gate", to: "c", when: "{{ nodes.a.output.ok == true }}" },
      ]
    );
    expect(codes(flow)).toEqual(
      expect.arrayContaining(["conditional-fields", "conditional-guards"])
    );
  });

  it("requires at least two edges out of a conditional node", () => {
    const flow = makeFlow(
      [tool("a"), { id: "gate", type: "conditional" }, tool("b")],
      [
        { from: "a", to: "gate" },
        { from: "gate", to: "b", when: "{{ nodes.a.output.ok == true }}" },
      ]
    );
    expect(codes(flow)).toContain("conditional-fanout");
  });

  it("flags unknown edge endpoints and mutually exclusive when/on", () => {
    const flow = makeFlow(
      [tool("a"), tool("b")],
      [
        { from: "a", to: "ghost" },
        { from: "a", to: "b", when: "{{ flow.input.x == 1 }}", on: "timeout" },
      ]
    );
    expect(codes(flow)).toEqual(expect.arrayContaining(["edge-endpoint", "edge-guard"]));
  });

  it("restricts on: timeout to human nodes with consistent timeoutSec/onTimeout", () => {
    const flow = makeFlow(
      [
        tool("a"),
        { id: "wait", type: "human", prompt: "Approve?", onTimeout: "a" },
        tool("b"),
      ],
      [
        { from: "a", to: "wait" },
        { from: "wait", to: "b", on: "timeout" },
        { from: "a", to: "b", on: "timeout" },
      ]
    );
    const found = codes(flow);
    expect(found).toContain("timeout-source"); // a is not human
    expect(found).toContain("timeout-missing"); // wait lacks timeoutSec
    expect(found).toContain("timeout-target"); // onTimeout !== edge target
  });

  it("flags onTimeout without a timeout edge and onTimeout on non-human nodes", () => {
    const flow = makeFlow(
      [
        { id: "wait", type: "human", prompt: "Approve?", timeoutSec: 5, onTimeout: "b" },
        { ...tool("b"), onTimeout: "wait" },
      ],
      [{ from: "wait", to: "b" }]
    );
    const found = codes(flow);
    expect(found).toContain("timeout-edge-missing");
    expect(found).toContain("on-timeout");
  });

  it("requires exactly one entry node and at least one terminal node", () => {
    const twoEntries = makeFlow(
      [tool("a"), tool("b"), tool("c")],
      [
        { from: "a", to: "c" },
        { from: "b", to: "c" },
      ]
    );
    expect(codes(twoEntries)).toContain("entry-node");

    const noTerminal = makeFlow(
      [tool("a"), tool("b")],
      [
        { from: "a", to: "b" },
        { from: "b", to: "a", when: "{{ nodes.b.output.retry == true }}" },
      ]
    );
    // guarded cycle is fine, but every node has outgoing edges
    expect(codes(noTerminal)).toContain("terminal-node");
  });

  it("flags unreachable nodes", () => {
    const flow = makeFlow(
      [tool("a"), tool("b"), tool("island"), tool("island-2")],
      [
        { from: "a", to: "b" },
        { from: "island", to: "island-2" },
      ]
    );
    // two entry candidates -> entry-node error; reachability then skipped
    expect(codes(flow)).toContain("entry-node");

    const single = makeFlow(
      [tool("a"), tool("b"), tool("island")],
      [
        { from: "a", to: "b" },
        { from: "b", to: "island", when: "{{ nodes.a.output.ok == true }}" },
        { from: "island", to: "a", when: "{{ nodes.a.output.ok == false }}" },
      ]
    );
    expect(codes(single)).not.toContain("unreachable");
  });

  it("rejects unconditional cycles but allows guarded rework loops", () => {
    const unconditional = makeFlow(
      [tool("a"), tool("b"), tool("c")],
      [
        { from: "a", to: "b" },
        { from: "b", to: "a" },
        { from: "b", to: "c", when: "{{ nodes.b.output.done == true }}" },
      ]
    );
    expect(codes(unconditional)).toContain("unconditional-cycle");

    const guarded = makeFlow(
      [tool("a"), tool("b"), tool("c")],
      [
        { from: "a", to: "b" },
        { from: "b", to: "a", when: "{{ nodes.b.output.retry == true }}" },
        { from: "b", to: "c" },
      ]
    );
    expect(codes(guarded)).not.toContain("unconditional-cycle");
  });

  it("rejects implicit parallel fan-out (two unguarded edges)", () => {
    const flow = makeFlow(
      [tool("a"), tool("b"), tool("c")],
      [
        { from: "a", to: "b" },
        { from: "a", to: "c" },
      ]
    );
    expect(codes(flow)).toContain("implicit-fanout");
  });

  it("checks expression state roots in when guards and bindings", () => {
    const flow = makeFlow(
      [
        { ...tool("a"), input: { x: "{{ nodes.ghost.output.y }}", y: "{{ item }}" } },
        tool("b"),
      ],
      [
        { from: "a", to: "b", when: "{{ flow.output.z == 1 }}" },
      ]
    );
    const found = codes(flow);
    expect(found).toContain("expr-unknown-node");
    expect(found).toContain("expr-item-scope"); // item outside map bindings
    expect(found).toContain("expr-flow-root"); // flow.output is not addressable
  });

  it("allows item bindings inside map nodes and only nodes.<id>.output paths", () => {
    const okFlow = makeFlow(
      [
        tool("a"),
        {
          id: "fan",
          type: "map",
          ref: "ns/skill-x",
          over: "{{ nodes.a.output.items }}",
          input: { value: "{{ item }}" },
        },
      ],
      [{ from: "a", to: "fan" }]
    );
    expect(codes(okFlow)).not.toContain("expr-item-scope");

    const badPath = makeFlow(
      [tool("a"), tool("b")],
      [{ from: "a", to: "b", when: "{{ nodes.a.state.ok == true }}" }]
    );
    expect(codes(badPath)).toContain("expr-node-output");
  });

  it("validates retry policies", () => {
    const flow = makeFlow(
      [{ ...tool("a"), retries: { maxAttempts: 0, backoff: "linear" as never, initialDelaySec: -1 } }],
      [],
      { defaults: { retries: { maxAttempts: 2.5 } } }
    );
    const messages = validateFlow(flow)
      .filter((issue) => issue.code === "retries")
      .map((issue) => issue.message);
    expect(messages).toHaveLength(4);
  });
});
