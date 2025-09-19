"use client";

import { FormEvent, useEffect, useState } from "react";

import ChatLayout from "../components/ChatLayout";
import MessageList, { type Message } from "../components/MessageList";
import PlanSidebar from "../components/PlanSidebar";
import { requestPlan, sendChatMessage } from "../lib/api";

export default function Page() {
  return <ChatExperience />;
}

function ChatExperience() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [plan, setPlan] = useState<string[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pendingMessage, setPendingMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function bootstrap() {
      try {
        const response = await requestPlan("Bootstrap AutoDev project");
        setSessionId(response.session_id);
        setPlan(response.plan);
        setMessages([
          {
            author: "Planner",
            content: `Initial plan created for goal: ${response.goal}`,
          },
        ]);
      } catch (err) {
        setError("Failed to fetch initial plan");
      }
    }

    void bootstrap();
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sessionId || !pendingMessage.trim()) {
      return;
    }

    setIsLoading(true);
    setError(null);

    const userMessage: Message = { author: "You", content: pendingMessage };
    setMessages((current) => [...current, userMessage]);

    try {
      const response = await sendChatMessage(sessionId, pendingMessage);
      const agentMessages: Message[] = response.results.map((result) => ({
        author: result.agent,
        content: result.content,
      }));
      setMessages((current) => [...current, ...agentMessages]);
    } catch (err) {
      setError("Unable to contact orchestrator API");
    } finally {
      setPendingMessage("");
      setIsLoading(false);
    }
  }

  return (
    <ChatLayout sidebar={<PlanSidebar plan={plan} />}>
      <div>
        <h1>AutoDev Architect</h1>
        <p className="subtitle">
          Coordinate planner, coding and DevOps agents from a single interface.
        </p>
      </div>

      <MessageList messages={messages} />

      <form className="chat-composer" onSubmit={handleSubmit}>
        <textarea
          value={pendingMessage}
          placeholder="Describe the next action for the agents"
          onChange={(event) => setPendingMessage(event.target.value)}
        />
        <button type="submit" disabled={!sessionId || isLoading}>
          {isLoading ? "Thinking..." : "Send"}
        </button>
      </form>

      {error ? <p role="alert">{error}</p> : null}
    </ChatLayout>
  );
}
