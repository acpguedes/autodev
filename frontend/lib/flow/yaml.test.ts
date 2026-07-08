import { describe, expect, it } from "vitest";

import { SAMPLE_FLOW, SAMPLE_FLOW_YAML } from "./sample";
import { parseFlowYaml, serializeFlowYaml } from "./yaml";

describe("parseFlowYaml", () => {
  it("parses the canonical sample without loss", () => {
    const result = parseFlowYaml(SAMPLE_FLOW_YAML);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.manifest).toEqual(SAMPLE_FLOW);
    }
  });

  it("reports YAML syntax errors", () => {
    const result = parseFlowYaml("nodes: [\n");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors[0]).toMatch(/YAML syntax error/);
    }
  });

  it("reports missing required top-level fields", () => {
    const result = parseFlowYaml("name: incomplete\n");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors).toEqual(
        expect.arrayContaining([
          'missing required top-level field "schemaVersion"',
          'missing required top-level field "id"',
          'missing required top-level field "version"',
          'missing required top-level field "hostApi"',
          'top-level field "nodes" must be a list',
          'top-level field "edges" must be a list',
        ])
      );
    }
  });

  it("normalizes the YAML 1.1 bare-on-as-boolean quirk on edges and triggers", () => {
    const text = [
      'schemaVersion: "1"',
      "id: ns/flow",
      "version: 1.0.0",
      'hostApi: ">=2.0 <3.0"',
      "triggers:",
      "  - type: event",
      "    true: flow.run.requested", // what PyYAML would produce for bare `on:`
      "nodes:",
      "  - id: wait",
      "    type: human",
      "    prompt: Approve?",
      "    timeoutSec: 60",
      "  - id: done",
      "    type: tool",
      "    ref: ns/tool-x",
      "edges:",
      "  - from: wait",
      "    to: done",
      "    true: timeout",
    ].join("\n");
    const result = parseFlowYaml(text);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.manifest.edges[0].on).toBe("timeout");
      expect(result.manifest.triggers?.[0].on).toBe("flow.run.requested");
    }
  });
});

describe("serializeFlowYaml (deterministic round-trip)", () => {
  it("is idempotent: serialize(parse(serialize(m))) === serialize(m)", () => {
    const first = serializeFlowYaml(SAMPLE_FLOW);
    const reparsed = parseFlowYaml(first);
    expect(reparsed.ok).toBe(true);
    if (reparsed.ok) {
      expect(serializeFlowYaml(reparsed.manifest)).toBe(first);
    }
  });

  it("normalizes key order regardless of input spelling", () => {
    const shuffled = [
      "edges:",
      "  - to: b",
      "    from: a",
      "nodes:",
      "  - type: tool",
      "    ref: ns/tool-a",
      "    id: a",
      "  - ref: ns/tool-b",
      "    id: b",
      "    type: tool",
      'hostApi: ">=2.0 <3.0"',
      "version: 1.0.0",
      "id: ns/flow",
      'schemaVersion: "1"',
    ].join("\n");
    const canonical = [
      'schemaVersion: "1"',
      "id: ns/flow",
      "version: 1.0.0",
      'hostApi: ">=2.0 <3.0"',
      "nodes:",
      "  - id: a",
      "    type: tool",
      "    ref: ns/tool-a",
      "  - id: b",
      "    type: tool",
      "    ref: ns/tool-b",
      "edges:",
      "  - from: a",
      "    to: b",
      "",
    ].join("\n");
    const result = parseFlowYaml(shuffled);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(serializeFlowYaml(result.manifest)).toBe(canonical);
    }
  });

  it("preserves unknown extension keys through the round-trip", () => {
    const result = parseFlowYaml(SAMPLE_FLOW_YAML);
    expect(result.ok).toBe(true);
    if (!result.ok) {
      return;
    }
    const manifest = {
      ...result.manifest,
      "x-custom": { anything: true },
      nodes: [{ ...result.manifest.nodes[0], "x-note": "keep me" }, ...result.manifest.nodes.slice(1)],
    };
    const text = serializeFlowYaml(manifest);
    const back = parseFlowYaml(text);
    expect(back.ok).toBe(true);
    if (back.ok) {
      expect(back.manifest["x-custom"]).toEqual({ anything: true });
      expect(back.manifest.nodes[0]["x-note"]).toBe("keep me");
    }
  });
});
