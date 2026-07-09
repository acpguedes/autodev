// Fixture data and a `window.fetch` stub shared by the Extensions hub
// Storybook stories (E17-S5 DoD: "Storybook stories for all states"). These
// components read exclusively through `lib/api_v2.ts` (API-first), so the
// stub only needs to answer `/v2/extensions*` requests to exercise the real
// component/network wiring without a live backend.

import type {
  AgentExtensionV2,
  AgentUpsertPayloadV2,
  ExtensionCatalogV2,
  ExtensionItemV2,
} from "@/lib/api_v2";

/** Sample catalog items covering every kind, and both enabled states. */
export const MOCK_EXTENSION_ITEMS: readonly ExtensionItemV2[] = [
  {
    kind: "agent",
    id: "reviewer",
    name: "Reviewer",
    enabled: true,
    pluginId: null,
    detail: { version: "1.2.0", capabilities: ["code-review", "security"] },
  },
  {
    kind: "agent",
    id: "planner",
    name: "Planner",
    enabled: false,
    pluginId: null,
    detail: { version: "1.0.0", capabilities: ["planning"] },
  },
  {
    kind: "skill",
    id: "summarize-diff",
    name: "Summarize diff",
    enabled: true,
    pluginId: "core-skills",
    detail: { version: "0.4.1", triggers: ["patch.created"] },
  },
  {
    kind: "plugin",
    id: "github-integration",
    name: "GitHub integration",
    enabled: false,
    pluginId: null,
    detail: { version: "2.0.0", extensionPoints: ["patch.review", "session.notify"] },
  },
  {
    kind: "mcp",
    id: "summarize-diff",
    name: "Summarize diff (MCP)",
    enabled: true,
    pluginId: "core-skills",
    detail: { transport: "stdio" },
  },
];

/**
 * Build a paginated catalog document from {@link MOCK_EXTENSION_ITEMS}.
 *
 * @returns A fixture `ExtensionCatalogV2` document.
 */
export function mockExtensionCatalog(): ExtensionCatalogV2 {
  return {
    schemaVersion: "1.0",
    items: [...MOCK_EXTENSION_ITEMS],
    page: { limit: 500, offset: 0, total: MOCK_EXTENSION_ITEMS.length },
  };
}

/**
 * Build the full agent manifest detail for one of the agent fixtures.
 *
 * @param agentId - Which agent fixture to build detail for; defaults to
 *   `"reviewer"` and falls back to the first fixture item for unknown ids.
 * @returns A fixture `AgentExtensionV2` document.
 */
export function mockAgentExtension(agentId = "reviewer"): AgentExtensionV2 {
  const item =
    MOCK_EXTENSION_ITEMS.find(
      (candidate) => candidate.kind === "agent" && candidate.id === agentId
    ) ?? MOCK_EXTENSION_ITEMS[0];
  return {
    schemaVersion: "1.0",
    item,
    systemPrompt: "You are a meticulous code reviewer. Flag correctness and security issues.",
    model: "claude-opus-4",
    allowedTools: ["read_file", "grep", "run_tests"],
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Install a `window.fetch` stub that answers every `/v2/extensions*` request
 * made by the Extensions hub components (catalog list, agent detail, agent
 * upsert, enable/disable). Requests for anything else fall through to the
 * previously installed `fetch`. Safe to call on every render — it just
 * reassigns `window.fetch`, which is idempotent.
 */
export function installExtensionsFetchMock(): void {
  const original = window.fetch.bind(window);
  window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();

    if (url.includes("/v2/extensions/agents/") && method === "PUT") {
      const agentId = decodeURIComponent(
        url.split("/v2/extensions/agents/")[1]?.split("?")[0] ?? "reviewer"
      );
      const payload = init?.body
        ? (JSON.parse(String(init.body)) as AgentUpsertPayloadV2)
        : undefined;
      const detail = mockAgentExtension(agentId);
      return jsonResponse({
        ...detail,
        item: { ...detail.item, name: payload?.displayName ?? detail.item.name },
        systemPrompt: payload?.systemPrompt ?? detail.systemPrompt,
        model: payload?.model ?? detail.model,
        allowedTools: payload?.allowedTools ?? detail.allowedTools,
      });
    }
    if (url.includes("/v2/extensions/agents/") && method === "GET") {
      const agentId = decodeURIComponent(
        url.split("/v2/extensions/agents/")[1]?.split("?")[0] ?? "reviewer"
      );
      return jsonResponse(mockAgentExtension(agentId));
    }
    const actionMatch = url.match(/\/v2\/extensions\/([^/]+)\/([^/]+)\/(enable|disable)/);
    if (actionMatch && method === "POST") {
      const [, kind, rawId, action] = actionMatch;
      const id = decodeURIComponent(rawId ?? "");
      const item =
        MOCK_EXTENSION_ITEMS.find(
          (candidate) => candidate.kind === kind && candidate.id === id
        ) ?? MOCK_EXTENSION_ITEMS[0];
      return jsonResponse({
        schemaVersion: "1.0",
        item: { ...item, enabled: action === "enable" },
      });
    }
    if (url.includes("/v2/extensions") && method === "GET") {
      return jsonResponse(mockExtensionCatalog());
    }
    return original(input, init);
  }) as typeof window.fetch;
}
