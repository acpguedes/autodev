// Typed client for the versioned Control Plane API (/v2) and the
// Prometheus /metrics endpoint, consumed by the E10-S2 screens
// (sessions/runs, catalogs, dashboards). Reuses the base-URL resolution
// from lib/api_ext.ts so every client resolves the backend identically.

import { buildUrl, requestJson } from "./api_ext";

// ---------------------------------------------------------------------------
// Sessions & runs (/v2/sessions)
// ---------------------------------------------------------------------------

/** Pagination metadata attached to every /v2 list response. */
export type PageMetaV2 = {
  limit: number;
  offset: number;
  total: number;
};

/** A single conversational turn within a session. */
export type HistoryItemV2 = {
  role: string;
  content: string;
};

/** Result produced by an agent during orchestration. */
export type AgentExecutionV2 = {
  agent: string;
  content: string;
  metadata: Record<string, unknown>;
};

/** A completed step (trace entry) within a run. */
export type RunStepV2 = {
  step_key: string;
  agent: string;
  status: string;
  started_at: string;
  completed_at: string;
  attempt: number;
};

/** A session, as returned by create/list/get on /v2/sessions. */
export type SessionV2 = {
  schemaVersion: string;
  session_id: string;
  goal: string;
  plan: string[];
  status: string;
  history: HistoryItemV2[];
};

/** Paginated collection of sessions. */
export type SessionListV2 = {
  schemaVersion: string;
  items: SessionV2[];
  page: PageMetaV2;
};

/** A single historical run, as returned by GET /v2/sessions/{id}/runs. */
export type RunV2 = {
  schemaVersion: string;
  run_id: string;
  session_id: string;
  status: string;
  run_type: string;
  current_state: string;
  trigger_message: string;
  created_at: string;
  results: AgentExecutionV2[];
  steps: RunStepV2[];
};

/** Paginated collection of runs. */
export type RunListV2 = {
  schemaVersion: string;
  items: RunV2[];
  page: PageMetaV2;
};

/**
 * List sessions from the v2 control plane.
 *
 * @param limit - Maximum number of sessions to return.
 * @param offset - Zero-based offset into the collection.
 * @returns The paginated session list.
 * @throws Error when the request fails.
 */
export async function listSessionsV2(limit = 100, offset = 0): Promise<SessionListV2> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return requestJson<SessionListV2>(`v2/sessions?${params.toString()}`);
}

/**
 * Create a new session for a high-level goal.
 *
 * @param goal - The operator's goal for the session.
 * @returns The created session.
 * @throws Error when the request fails.
 */
export async function createSessionV2(goal: string): Promise<SessionV2> {
  return requestJson<SessionV2>("v2/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal }),
  });
}

/**
 * Fetch a single session by id.
 *
 * @param sessionId - Session identifier.
 * @returns The session document.
 * @throws Error when the request fails (including 404).
 */
export async function getSessionV2(sessionId: string): Promise<SessionV2> {
  return requestJson<SessionV2>(`v2/sessions/${encodeURIComponent(sessionId)}`);
}

/**
 * List runs recorded for a session.
 *
 * @param sessionId - Session identifier.
 * @param limit - Maximum number of runs to return.
 * @param offset - Zero-based offset into the collection.
 * @returns The paginated run list.
 * @throws Error when the request fails.
 */
export async function listSessionRunsV2(
  sessionId: string,
  limit = 50,
  offset = 0
): Promise<RunListV2> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return requestJson<RunListV2>(
    `v2/sessions/${encodeURIComponent(sessionId)}/runs?${params.toString()}`
  );
}

/**
 * Build the SSE URL for a run's live event stream.
 *
 * @param runId - Run whose events should be streamed.
 * @param options - Optional tenant scope, event-type filter, and resume cursor.
 * @returns The absolute (or root-relative) stream URL.
 */
export function runEventsStreamUrl(
  runId: string,
  options: { tenantId?: string; types?: string[]; cursor?: string } = {}
): string {
  const params = new URLSearchParams();
  if (options.tenantId) {
    params.set("tenantId", options.tenantId);
  }
  if (options.types && options.types.length > 0) {
    params.set("types", options.types.join(","));
  }
  if (options.cursor) {
    params.set("cursor", options.cursor);
  }
  const query = params.toString();
  return buildUrl(`v2/runs/${encodeURIComponent(runId)}/events/stream${query ? `?${query}` : ""}`);
}

// ---------------------------------------------------------------------------
// Chat turns (/v2/sessions/{id}/turns, /v2/turns/{id}) — E16-S1
// ---------------------------------------------------------------------------

/**
 * One chat turn: a user message plus the run it triggered. `turnId` doubles
 * as the run id, so it can be passed to {@link runEventsStreamUrl}.
 */
export type TurnV2 = {
  schemaVersion: string;
  turnId: string;
  sessionId: string;
  message: string;
  status: string;
  runType: string;
  currentState: string;
  createdAt: string;
  history: HistoryItemV2[];
  results: AgentExecutionV2[];
  steps: RunStepV2[];
};

/** Paginated collection of turns, oldest first. */
export type TurnListV2 = {
  schemaVersion: string;
  items: TurnV2[];
  page: PageMetaV2;
};

/**
 * Create a turn: send a user message into a session and execute a run.
 *
 * @param sessionId - Session receiving the message.
 * @param message - The user message driving this turn.
 * @returns The completed turn, including agent results and trace steps.
 * @throws Error when the request fails (including 404 for unknown session).
 */
export async function createTurnV2(sessionId: string, message: string): Promise<TurnV2> {
  return requestJson<TurnV2>(`v2/sessions/${encodeURIComponent(sessionId)}/turns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}

/**
 * Fetch a single turn by its id.
 *
 * @param turnId - Turn (run) identifier.
 * @returns The turn document.
 * @throws Error when the request fails (including 404).
 */
export async function getTurnV2(turnId: string): Promise<TurnV2> {
  return requestJson<TurnV2>(`v2/turns/${encodeURIComponent(turnId)}`);
}

/**
 * List the turns recorded for a session, oldest first.
 *
 * @param sessionId - Session identifier.
 * @param limit - Maximum number of turns to return.
 * @param offset - Zero-based offset into the collection.
 * @returns The paginated turn list.
 * @throws Error when the request fails.
 */
export async function listSessionTurnsV2(
  sessionId: string,
  limit = 50,
  offset = 0
): Promise<TurnListV2> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return requestJson<TurnListV2>(
    `v2/sessions/${encodeURIComponent(sessionId)}/turns?${params.toString()}`
  );
}

// ---------------------------------------------------------------------------
// Provider status (/v2/provider-config/status) — E16-S4
// ---------------------------------------------------------------------------

/** Live provider status backing the composer's provider chip. */
export type ProviderStatusV2 = {
  schemaVersion: string;
  name: string;
  model: string;
  configured: boolean;
  healthy: boolean;
};

/**
 * Fetch the active LLM provider's status (name, model, health).
 *
 * @returns The provider status document.
 * @throws Error when the request fails.
 */
export async function getProviderStatusV2(): Promise<ProviderStatusV2> {
  return requestJson<ProviderStatusV2>("v2/provider-config/status");
}

// ---------------------------------------------------------------------------
// Catalogs (/v2/agents, /v2/skills, /v2/plugins)
// ---------------------------------------------------------------------------

/** A capability declared by an agent manifest. */
export type AgentCapabilityV2 = {
  id: string;
  version: string;
  level: string;
};

/** One agent registration in the agent catalog. */
export type AgentCatalogItemV2 = {
  id: string;
  version: string;
  pluginId: string | null;
  deprecated: boolean;
  deprecationReason: string | null;
  capabilities: AgentCapabilityV2[];
  io: { contract: string; contractVersion: string };
  rank: { score: number };
};

/** The agent catalog document. */
export type AgentCatalogV2 = {
  schemaVersion: string;
  agents: AgentCatalogItemV2[];
};

/** One skill registration in the skill catalog. */
export type SkillCatalogItemV2 = {
  id: string;
  version: string;
  pluginId: string | null;
  kind: string;
  deprecated: boolean;
  deprecationReason: string | null;
  triggers: string[];
  permissions: Record<string, unknown>;
};

/** The skill catalog document. */
export type SkillCatalogV2 = {
  schemaVersion: string;
  skills: SkillCatalogItemV2[];
};

/** An extension point inhabited by an active plugin. */
export type PluginExtensionPointV2 = {
  kind: string;
  id: string;
  contract: string;
};

/** One active plugin in the plugin registry snapshot. */
export type ActivePluginV2 = {
  id: string;
  version: string;
  state: string;
  extensionPoints: PluginExtensionPointV2[];
};

/** The active-plugin registry snapshot document. */
export type ActivePluginsV2 = {
  schemaVersion: string;
  activePlugins: ActivePluginV2[];
  inhabitedExtensionPoints: Array<{ kind: string; pluginIds: string[] }>;
};

/**
 * Fetch the agent catalog, optionally filtered by capability.
 *
 * @param capability - Restrict to agents declaring this capability.
 * @returns The agent catalog document.
 * @throws Error when the request fails.
 */
export async function getAgentCatalogV2(capability?: string): Promise<AgentCatalogV2> {
  const query = capability ? `?${new URLSearchParams({ capability }).toString()}` : "";
  return requestJson<AgentCatalogV2>(`v2/agents/catalog${query}`);
}

/**
 * Fetch the full skill catalog.
 *
 * @returns The skill catalog document.
 * @throws Error when the request fails.
 */
export async function getSkillCatalogV2(): Promise<SkillCatalogV2> {
  return requestJson<SkillCatalogV2>("v2/skills");
}

/**
 * Fetch the active-plugin registry snapshot.
 *
 * @returns The active plugins document.
 * @throws Error when the request fails.
 */
export async function getActivePluginsV2(): Promise<ActivePluginsV2> {
  return requestJson<ActivePluginsV2>("v2/plugins/active");
}

// ---------------------------------------------------------------------------
// Observability metrics (/metrics, Prometheus text-exposition format)
// ---------------------------------------------------------------------------

/** Aggregated request metrics for one (method, path) route. */
export type RouteMetric = {
  method: string;
  path: string;
  requests: number;
  errors: number;
  durationSeconds: number;
};

const METRIC_LINE_PATTERN =
  /^(http_requests_total|http_request_duration_seconds|http_request_errors_total)\{method="([^"]*)",path="([^"]*)"\}\s+(\S+)$/;

/**
 * Parse the backend's Prometheus text-exposition output into per-route rows.
 *
 * Unknown metric names and comment lines are ignored; malformed values
 * parse as 0 so a partially corrupt exposition never throws.
 *
 * @param text - Raw body of GET /metrics.
 * @returns One aggregated row per (method, path) route, sorted by request
 *   count descending.
 */
export function parsePrometheusMetrics(text: string): RouteMetric[] {
  const routes = new Map<string, RouteMetric>();
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }
    const match = METRIC_LINE_PATTERN.exec(line);
    if (!match) {
      continue;
    }
    const [, metric, method, path, rawValue] = match;
    const value = Number(rawValue);
    const numeric = Number.isFinite(value) ? value : 0;
    const key = `${method} ${path}`;
    let entry = routes.get(key);
    if (!entry) {
      entry = { method, path, requests: 0, errors: 0, durationSeconds: 0 };
      routes.set(key, entry);
    }
    if (metric === "http_requests_total") {
      entry.requests = numeric;
    } else if (metric === "http_request_errors_total") {
      entry.errors = numeric;
    } else {
      entry.durationSeconds = numeric;
    }
  }
  return Array.from(routes.values()).sort((a, b) => b.requests - a.requests);
}

/**
 * Fetch the raw Prometheus metrics exposition from the backend.
 *
 * @returns The /metrics response body as text.
 * @throws Error when the request fails.
 */
export async function getMetricsText(): Promise<string> {
  const response = await fetch(buildUrl("metrics"));
  if (!response.ok) {
    throw new Error(`Request failed for /metrics (${response.status})`);
  }
  return response.text();
}

// ---------------------------------------------------------------------------
// Server-Sent Events framing
// ---------------------------------------------------------------------------

/** One decoded SSE frame from a run event stream. */
export type SseFrame = {
  id: string | null;
  event: string | null;
  data: string;
};

/**
 * Extract complete SSE frames from an accumulating text buffer.
 *
 * Frames are separated by a blank line; the trailing partial frame (if any)
 * is returned as `rest` so callers can carry it into the next chunk.
 * Comment lines (starting with ":") are ignored, which also filters the
 * server's `: ping` heartbeats.
 *
 * @param buffer - Accumulated stream text (previous rest + new chunk).
 * @returns The decoded complete frames and the unconsumed remainder.
 */
export function parseSseBuffer(buffer: string): { frames: SseFrame[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const segments = normalized.split("\n\n");
  const rest = segments.pop() ?? "";
  const frames: SseFrame[] = [];
  for (const segment of segments) {
    let id: string | null = null;
    let event: string | null = null;
    const dataLines: string[] = [];
    for (const line of segment.split("\n")) {
      if (!line || line.startsWith(":")) {
        continue;
      }
      const separator = line.indexOf(":");
      const field = separator === -1 ? line : line.slice(0, separator);
      let value = separator === -1 ? "" : line.slice(separator + 1);
      if (value.startsWith(" ")) {
        value = value.slice(1);
      }
      if (field === "id") {
        id = value;
      } else if (field === "event") {
        event = value;
      } else if (field === "data") {
        dataLines.push(value);
      }
    }
    if (id !== null || event !== null || dataLines.length > 0) {
      frames.push({ id, event, data: dataLines.join("\n") });
    }
  }
  return { frames, rest };
}
