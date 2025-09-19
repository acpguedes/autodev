export type PlanResponse = {
  session_id: string;
  goal: string;
  plan: string[];
};

export type ChatResponse = {
  session_id: string;
  history: string[];
  results: { agent: string; content: string; metadata?: Record<string, unknown> }[];
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function requestPlan(goal: string): Promise<PlanResponse> {
  const response = await fetch(`${API_BASE_URL}/plan`, {
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
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });

  if (!response.ok) {
    throw new Error("Failed to send chat message");
  }

  return (await response.json()) as ChatResponse;
}
