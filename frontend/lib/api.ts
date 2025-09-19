export type PlanResponse = {
  session_id: string;
  goal: string;
  plan: string[];
};

export type ChatHistoryItem = {
  role: string;
  content: string;
};

export type ChatResponse = {
  session_id: string;
  history: ChatHistoryItem[];
  results: { agent: string; content: string; metadata?: Record<string, unknown> }[];
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

export async function requestPlan(goal: string): Promise<PlanResponse> {
  const response = await fetch(buildApiUrl("plan"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal }),
  });

  if (!response.ok) {
    throw new Error("Failed to create plan");
  }

  return (await response.json()) as PlanResponse;
}

export async function sendChatMessage(sessionId: string, message: string): Promise<ChatResponse> {
  const response = await fetch(buildApiUrl("chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });

  if (!response.ok) {
    throw new Error("Failed to send chat message");
  }

  return (await response.json()) as ChatResponse;
}
