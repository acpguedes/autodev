// Typed API client for the new platform subsystems (skills, agents, plans,
// patches). Kept separate from lib/api.ts so the original client is untouched.

const stripTrailingSlash = (url: string): string => url.replace(/\/+$/, "");

const resolveBaseUrl = (): string => {
  const envUrl = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (envUrl) {
    return stripTrailingSlash(envUrl);
  }
  if (typeof window !== "undefined" && window.location) {
    const { hostname, origin, port, protocol } = window.location;
    if ((hostname === "localhost" || hostname === "127.0.0.1") && port === "3000") {
      return `${protocol}//${hostname}:8000`;
    }
    return stripTrailingSlash(origin);
  }
  return "";
};

const API_BASE_URL = resolveBaseUrl();

const buildUrl = (path: string): string => {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return API_BASE_URL ? `${API_BASE_URL}${normalized}` : normalized;
};

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildUrl(path), init);
  if (!response.ok) {
    throw new Error(`Request failed for ${path} (${response.status})`);
  }
  return (await response.json()) as T;
}

export type SkillSummary = {
  name: string;
  description: string;
};

export type AgentSummary = {
  name: string;
  has_contract?: boolean;
};

export type PlanDocument = {
  session_id: string;
  steps: string[];
  status: string;
  updated_at?: string;
};

export type PatchResult = {
  path: string;
  original: string;
  updated: string;
  diff: string;
};

export async function listSkills(): Promise<SkillSummary[]> {
  return requestJson<SkillSummary[]>("skills");
}

export async function listAgents(): Promise<AgentSummary[]> {
  return requestJson<AgentSummary[]>("agents");
}

export async function getPlan(sessionId: string): Promise<PlanDocument> {
  return requestJson<PlanDocument>(`plans/${sessionId}`);
}

export async function generatePatch(
  path: string,
  original: string,
  updated: string
): Promise<PatchResult> {
  return requestJson<PatchResult>("patches/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, original, updated }),
  });
}
