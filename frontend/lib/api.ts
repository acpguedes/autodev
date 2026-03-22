export type PlanResponse = {
  session_id: string;
  goal: string;
  plan: string[];
  status: string;
};

export type ChatHistoryItem = {
  role: string;
  content: string;
};

export type AgentExecution = {
  agent: string;
  content: string;
  metadata?: Record<string, unknown>;
};

export type ChatResponse = {
  run_id: string;
  session_id: string;
  status: string;
  run_type: string;
  current_state: string;
  history: ChatHistoryItem[];
  results: AgentExecution[];
  steps: RunStep[];
};

export type RunStep = {
  step_key: string;
  agent: string;
  status: string;
  started_at: string;
  completed_at: string;
  attempt: number;
};

export type SessionResponse = {
  session_id: string;
  goal: string;
  plan: string[];
  status: string;
  history: ChatHistoryItem[];
};

export type RunResponse = {
  run_id: string;
  session_id: string;
  status: string;
  run_type: string;
  current_state: string;
  trigger_message: string;
  created_at: string;
  results: AgentExecution[];
  steps: RunStep[];
};

export type RepositoryFileMatch = {
  path: string;
  score: number;
  reasons: string[];
};

export type RepositoryContextResponse = {
  query: string;
  root: string;
  total_files: number;
  top_directories: string[];
  candidate_files: RepositoryFileMatch[];
  inventory_sample: string[];
  matched_terms: string[];
};

export type RuntimeConfig = {
  version: number;
  llm: {
    provider: string;
    model: string;
    base_url: string;
    temperature: number;
    api_key: string;
  };
  repository: {
    project_root: string;
    repository_label: string;
    default_goal: string;
  };
};

export type RuntimeInstructions = {
  config_path: string;
  config_file_example: string;
  env_file_example: string;
  notes: string[];
};

export type RuntimeConfigResponse = {
  config: RuntimeConfig;
  instructions: RuntimeInstructions;
};

const normalizeBaseUrl = (url: string | undefined): string | undefined => {
  if (!url) {
    return undefined;
  }

  const trimmed = url.trim();
  if (!trimmed) {
    return undefined;
  }

  return trimmed.replace(/\/+$/, "");
};

const getDefaultApiBaseUrl = (): string => {
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin.replace(/\/+$/, "");
  }

  return "";
};

const API_BASE_URL = normalizeBaseUrl(process.env.NEXT_PUBLIC_API_URL) ?? getDefaultApiBaseUrl();

const ensureLeadingSlash = (path: string): string =>
  path.startsWith("/") ? path : `/${path}`;

const buildApiUrl = (path: string): string => {
  const normalizedPath = ensureLeadingSlash(path);

  if (!API_BASE_URL) {
    if (typeof window === "undefined") {
      throw new Error(
        "API base URL is not configured. Set NEXT_PUBLIC_API_URL for server-side usage."
      );
    }

    return normalizedPath;
  }

  return `${API_BASE_URL}${normalizedPath}`;
};

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildApiUrl(path), init);

  if (!response.ok) {
    throw new Error(`Request failed for ${path}`);
  }

  return (await response.json()) as T;
}

export async function getRuntimeConfig(): Promise<RuntimeConfigResponse> {
  return requestJson<RuntimeConfigResponse>("config");
}

export async function updateRuntimeConfig(config: RuntimeConfig): Promise<RuntimeConfigResponse> {
  return requestJson<RuntimeConfigResponse>("config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
}

export async function requestPlan(goal: string): Promise<PlanResponse> {
  return requestJson<PlanResponse>("plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal }),
  });
}

export async function sendChatMessage(sessionId: string, message: string): Promise<ChatResponse> {
  return requestJson<ChatResponse>("chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
}

export async function listSessions(): Promise<SessionResponse[]> {
  return requestJson<SessionResponse[]>("sessions");
}

export async function listRuns(sessionId: string): Promise<RunResponse[]> {
  return requestJson<RunResponse[]>(`sessions/${sessionId}/runs`);
}

export async function getRepositoryContext(
  query: string,
  limit = 6
): Promise<RepositoryContextResponse> {
  const params = new URLSearchParams({ query, limit: String(limit) });
  return requestJson<RepositoryContextResponse>(`repository/context?${params.toString()}`);
}
