"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import ChatLayout from "../components/ChatLayout";
import ExecutionPlanPanel from "../components/ExecutionPlanPanel";
import MessageList, { type Message } from "../components/MessageList";
import PlanSidebar from "../components/PlanSidebar";
import RunHistoryPanel from "../components/RunHistoryPanel";
import {
  type ExecutionPlanResponse,
  type RepositoryContextResponse,
  type RunResponse,
  type RuntimeConfig,
  type SessionResponse,
  executePlan,
  getExecutionPlan,
  getRepositoryContext,
  getRuntimeConfig,
  listRuns,
  listSessions,
  requestPlan,
  sendChatMessage,
} from "../lib/api";

const DEFAULT_REPOSITORY_QUERY = "configuração llm repositório projeto";

export default function Page() {
  return <ExecutionControlCenter />;
}

function ExecutionControlCenter() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [plan, setPlan] = useState<string[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pendingMessage, setPendingMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isExecutingPlan, setIsExecutingPlan] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [sessions, setSessions] = useState<SessionResponse[]>([]);
  const [runs, setRuns] = useState<RunResponse[]>([]);
  const [repositoryContext, setRepositoryContext] =
    useState<RepositoryContextResponse | null>(null);
  const [executionPlan, setExecutionPlan] = useState<ExecutionPlanResponse | null>(null);

  useEffect(() => {
    async function bootstrap() {
      try {
        const runtime = await getRuntimeConfig();
        setConfig(runtime.config);

        const existingSessions = await listSessions();
        setSessions(existingSessions);

        if (existingSessions.length > 0) {
          const latestSession = existingSessions[0];
          setSessionId(latestSession.session_id);
          setPlan(latestSession.plan);
          setMessages(mapHistoryToMessages(latestSession.history));
          setRuns(await listRuns(latestSession.session_id));
          setExecutionPlan(await getExecutionPlan(latestSession.session_id));
        } else {
          const planResponse = await requestPlan(runtime.config.repository.default_goal);
          setSessionId(planResponse.session_id);
          setPlan(planResponse.plan);
          setMessages([
            {
              author: "Planner",
              content: `Initial plan created for goal: ${planResponse.goal}`,
            },
          ]);
          setSessions(await listSessions());
          setExecutionPlan(await getExecutionPlan(planResponse.session_id));
        }

        setRepositoryContext(await getRepositoryContext(DEFAULT_REPOSITORY_QUERY));
      } catch {
        setError("Failed to bootstrap the execution control center.");
      }
    }

    void bootstrap();
  }, []);

  const currentWorkspaceLabel = config?.repository.repository_label;
  const currentProjectRoot = config?.repository.project_root;

  async function refreshSessionState(activeSessionId: string) {
    const refreshedSessions = await listSessions();
    setSessions(refreshedSessions);
    setRuns(await listRuns(activeSessionId));
    setExecutionPlan(await getExecutionPlan(activeSessionId));
  }

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
      setMessages(mapHistoryToMessages(response.history));
      await refreshSessionState(sessionId);
    } catch {
      setError("Unable to contact orchestrator API.");
    } finally {
      setPendingMessage("");
      setIsLoading(false);
    }
  }

  async function handleCreateSession() {
    if (!config) {
      return;
    }

    setError(null);

    try {
      const response = await requestPlan(config.repository.default_goal);
      setSessionId(response.session_id);
      setPlan(response.plan);
      setRuns([]);
      setMessages([
        {
          author: "Planner",
          content: `Initial plan created for goal: ${response.goal}`,
        },
      ]);
      setSessions(await listSessions());
      setExecutionPlan(await getExecutionPlan(response.session_id));
    } catch {
      setError("Unable to create a new planning session.");
    }
  }

  async function handleExecutePlan() {
    if (!sessionId) {
      return;
    }

    setIsExecutingPlan(true);
    setError(null);

    try {
      const response = await executePlan(sessionId);
      setMessages(mapHistoryToMessages(response.history));
      await refreshSessionState(sessionId);
    } catch {
      setError("Unable to execute the generated plan.");
    } finally {
      setIsExecutingPlan(false);
    }
  }

  return (
    <ChatLayout
      currentView="dashboard"
      sidebar={
        <PlanSidebar
          plan={plan}
          sessionId={sessionId}
          status={runs[0]?.status ?? executionPlan?.status ?? "awaiting_input"}
          repositoryLabel={currentWorkspaceLabel}
          projectRoot={currentProjectRoot}
        />
      }
    >
      <section className="hero-card">
        <div>
          <p className="eyebrow">Release 0.6 workflow slice</p>
          <h1>AutoDev Architect control center</h1>
          <p className="subtitle">
            Review the current plan, derive a post-analysis execution backlog, and run each task in
            sequence from the main dashboard.
          </p>
        </div>
        <div className="hero-card__actions">
          <Link className="secondary-button secondary-button--link" href="/config">
            Open config workspace
          </Link>
          <button className="secondary-button" type="button" onClick={handleCreateSession}>
            New planning session
          </button>
        </div>
      </section>

      <ExecutionPlanPanel
        executionPlan={executionPlan}
        isExecuting={isExecutingPlan}
        onExecute={handleExecutePlan}
      />

      <div className="panel-grid panel-grid--two-up">
        <section className="panel-card">
          <div className="panel-card__header">
            <div>
              <p className="eyebrow">Repository intelligence</p>
              <h2>Context preview for the active project</h2>
            </div>
          </div>

          {repositoryContext ? (
            <div className="repository-context">
              <p className="run-card__meta">
                Root: {repositoryContext.root} · Files: {repositoryContext.total_files}
              </p>
              <div className="tag-list">
                {repositoryContext.top_directories.map((directory) => (
                  <span className="tag" key={directory}>
                    {directory}
                  </span>
                ))}
              </div>
              <div className="candidate-list">
                {repositoryContext.candidate_files.map((file) => (
                  <article className="candidate-card" key={file.path}>
                    <strong>{file.path}</strong>
                    <p>score {file.score}</p>
                    <p>{file.reasons.join(" · ")}</p>
                  </article>
                ))}
              </div>
            </div>
          ) : (
            <p className="empty-state">Loading repository context...</p>
          )}
        </section>

        <RunHistoryPanel runs={runs} />
      </div>

      <section className="panel-card">
        <div className="panel-card__header">
          <div>
            <p className="eyebrow">Agent console</p>
            <h2>Conversation and execution log</h2>
          </div>
          <p className="run-card__meta">Known sessions: {sessions.length}</p>
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
      </section>

      {error ? <p role="alert" className="error-banner">{error}</p> : null}
    </ChatLayout>
  );
}

function mapHistoryToMessages(history: { role: string; content: string }[]): Message[] {
  if (history.length === 0) {
    return [];
  }

  return history.map((entry) => ({
    author: entry.role === "user" ? "You" : entry.role,
    content: entry.content,
  }));
}
