/**
 * Deterministic `flow.yaml` <-> `FlowManifest` round-trip (E10-S3-T2).
 *
 * - `parseFlowYaml` accepts any YAML spelling (key order, quoting, the
 *   YAML 1.1 bare-`on`-as-boolean quirk) and produces a normalized manifest.
 * - `serializeFlowYaml` always emits the same canonical document for the
 *   same manifest: fixed key order per object, 2-space indent, unknown keys
 *   preserved after the known ones in their original order.
 *
 * Determinism guarantee: serialize(parse(serialize(m))) === serialize(m).
 */

import { parse, stringify } from "yaml";

import type { FlowEdge, FlowManifest, FlowNode, FlowTrigger } from "./types";

export type ParseSuccess = { ok: true; manifest: FlowManifest };
export type ParseFailure = { ok: false; errors: string[] };
export type ParseResult = ParseSuccess | ParseFailure;

const TOP_LEVEL_ORDER = [
  "schemaVersion",
  "id",
  "version",
  "name",
  "description",
  "hostApi",
  "triggers",
  "input",
  "output",
  "defaults",
  "nodes",
  "edges",
  "budgets",
] as const;

const NODE_ORDER = [
  "id",
  "type",
  "ref",
  "prompt",
  "form",
  "over",
  "reduce",
  "maxParallel",
  "input",
  "timeoutSec",
  "onTimeout",
  "retries",
] as const;

const EDGE_ORDER = ["from", "to", "when", "on"] as const;

const TRIGGER_ORDER = ["type", "schedule", "on"] as const;

const RETRIES_ORDER = ["maxAttempts", "backoff", "initialDelaySec"] as const;

const DEFAULTS_ORDER = ["retries", "timeoutSec"] as const;

const BUDGETS_ORDER = ["maxCostUsd", "maxWallClockSec", "maxTokens"] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * PyYAML (YAML 1.1) parses a bare `on:` key as boolean `true`. The `yaml`
 * package follows YAML 1.2 (string key), but we tolerate documents written
 * for either parser by renaming a `true` key back to `"on"`.
 */
function normalizeOnKey(entry: Record<string, unknown>): Record<string, unknown> {
  if (!("true" in entry) || "on" in entry) {
    return entry;
  }
  const normalized: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(entry)) {
    normalized[key === "true" ? "on" : key] = value;
  }
  return normalized;
}

function structuralErrors(doc: unknown): string[] {
  const errors: string[] = [];
  if (!isRecord(doc)) {
    return ["flow.yaml must contain a YAML mapping at the top level"];
  }
  for (const field of ["schemaVersion", "id", "version", "hostApi"] as const) {
    if (doc[field] === undefined || doc[field] === null) {
      errors.push(`missing required top-level field "${field}"`);
    }
  }
  for (const field of ["nodes", "edges"] as const) {
    if (!Array.isArray(doc[field])) {
      errors.push(`top-level field "${field}" must be a list`);
    }
  }
  if (Array.isArray(doc.nodes)) {
    doc.nodes.forEach((node, index) => {
      if (!isRecord(node)) {
        errors.push(`nodes[${index}] must be a mapping`);
      } else {
        if (typeof node.id !== "string" || node.id.length === 0) {
          errors.push(`nodes[${index}] is missing a string "id"`);
        }
        if (typeof node.type !== "string" || node.type.length === 0) {
          errors.push(`nodes[${index}] is missing a string "type"`);
        }
      }
    });
  }
  if (Array.isArray(doc.edges)) {
    doc.edges.forEach((edge, index) => {
      if (!isRecord(edge)) {
        errors.push(`edges[${index}] must be a mapping`);
      } else {
        const entry = normalizeOnKey(edge);
        if (typeof entry.from !== "string" || entry.from.length === 0) {
          errors.push(`edges[${index}] is missing a string "from"`);
        }
        if (typeof entry.to !== "string" || entry.to.length === 0) {
          errors.push(`edges[${index}] is missing a string "to"`);
        }
      }
    });
  }
  if (doc.triggers !== undefined && !Array.isArray(doc.triggers)) {
    errors.push('top-level field "triggers" must be a list');
  }
  return errors;
}

/** Parse YAML text into a normalized manifest, or structural errors. */
export function parseFlowYaml(text: string): ParseResult {
  let doc: unknown;
  try {
    doc = parse(text, { version: "1.2" });
  } catch (error) {
    return {
      ok: false,
      errors: [`YAML syntax error: ${error instanceof Error ? error.message : String(error)}`],
    };
  }

  const errors = structuralErrors(doc);
  if (errors.length > 0) {
    return { ok: false, errors };
  }

  const raw = doc as Record<string, unknown>;
  const manifest: FlowManifest = {
    ...raw,
    schemaVersion: String(raw.schemaVersion),
    id: String(raw.id),
    version: String(raw.version),
    hostApi: String(raw.hostApi),
    nodes: (raw.nodes as Record<string, unknown>[]).map((node) => ({ ...node }) as FlowNode),
    edges: (raw.edges as Record<string, unknown>[]).map(
      (edge) => normalizeOnKey(edge) as FlowEdge
    ),
  };
  if (Array.isArray(raw.triggers)) {
    manifest.triggers = raw.triggers.map((trigger) =>
      isRecord(trigger) ? (normalizeOnKey(trigger) as FlowTrigger) : (trigger as FlowTrigger)
    );
  }
  return { ok: true, manifest };
}

function orderKeys(
  value: Record<string, unknown>,
  order: readonly string[],
  transform?: (key: string, value: unknown) => unknown
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  const apply = (key: string, entry: unknown) =>
    transform ? transform(key, entry) : entry;
  for (const key of order) {
    if (value[key] !== undefined) {
      result[key] = apply(key, value[key]);
    }
  }
  for (const key of Object.keys(value)) {
    if (!order.includes(key) && value[key] !== undefined) {
      result[key] = apply(key, value[key]);
    }
  }
  return result;
}

function canonicalNode(node: FlowNode): Record<string, unknown> {
  return orderKeys(node, NODE_ORDER, (key, value) =>
    key === "retries" && isRecord(value) ? orderKeys(value, RETRIES_ORDER) : value
  );
}

function canonicalManifest(manifest: FlowManifest): Record<string, unknown> {
  return orderKeys(manifest, TOP_LEVEL_ORDER, (key, value) => {
    switch (key) {
      case "nodes":
        return (value as FlowNode[]).map(canonicalNode);
      case "edges":
        return (value as FlowEdge[]).map((edge) => orderKeys(edge, EDGE_ORDER));
      case "triggers":
        return (value as FlowTrigger[]).map((trigger) =>
          isRecord(trigger) ? orderKeys(trigger, TRIGGER_ORDER) : trigger
        );
      case "defaults":
        return isRecord(value)
          ? orderKeys(value, DEFAULTS_ORDER, (innerKey, innerValue) =>
              innerKey === "retries" && isRecord(innerValue)
                ? orderKeys(innerValue, RETRIES_ORDER)
                : innerValue
            )
          : value;
      case "budgets":
        return isRecord(value) ? orderKeys(value, BUDGETS_ORDER) : value;
      default:
        return value;
    }
  });
}

/** Serialize a manifest to canonical, deterministic YAML. */
export function serializeFlowYaml(manifest: FlowManifest): string {
  return stringify(canonicalManifest(manifest), {
    indent: 2,
    lineWidth: 0,
    aliasDuplicateObjects: false,
  });
}
