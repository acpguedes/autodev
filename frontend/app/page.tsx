"use client";

import { FormEvent, useEffect, useState } from "react";

import ChatLayout from "../components/ChatLayout";
import ExecutionConsolePanel from "../components/ExecutionConsolePanel";
import MessageList, { type Message } from "../components/MessageList";
import {
  type ExecutionPlanResponse,
  type RunResponse,
  type RuntimeConfig,
  type SessionResponse,
  executePlan,
  getExecutionPlan,
  getRuntimeConfig,
  listRuns,
  listSessions,
  requestPlan,
  sendChatMessage,
} from "../lib/api";

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
  const [executionPlan, setExecutionPlan] = useState<ExecutionPlanResponse | null>(null);
  const [isConsoleOpen, setIsConsoleOpen] = useState(false);

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
              content: `Plano inicial criado para o objetivo: ${planResponse.goal}`,
            },
          ]);
          setSessions(await listSessions());
          setExecutionPlan(await getExecutionPlan(planResponse.session_id));
        }
      } catch {
        setError("Não foi possível carregar o workspace de chat.");
      }
    }

    void bootstrap();
  }, []);

  const currentWorkspaceLabel = config?.repository.repository_label;
  const currentProjectRoot = config?.repository.project_root;
  const executionStatus = runs[0]?.status ?? executionPlan?.status ?? "awaiting_input";
  const isBusy = isLoading || isExecutingPlan;
  const hasConsoleEntries = runs.some((run) => run.results.length > 0);
  const showConsole = isConsoleOpen || isBusy || hasConsoleEntries;
  const nextTasks = executionPlan?.tasks.slice(0, 3) ?? [];

  useEffect(() => {
    if (isBusy || hasConsoleEntries) {
      setIsConsoleOpen(true);
    }
  }, [hasConsoleEntries, isBusy]);

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
      setError("Não foi possível enviar a mensagem para o orquestrador.");
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
          content: `Plano inicial criado para o objetivo: ${response.goal}`,
        },
      ]);
      setSessions(await listSessions());
      setExecutionPlan(await getExecutionPlan(response.session_id));
      setIsConsoleOpen(false);
    } catch {
      setError("Não foi possível criar uma nova sessão.");
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
      setError("Não foi possível executar o plano gerado.");
    } finally {
      setIsExecutingPlan(false);
    }
  }

  return (
    <ChatLayout currentView="dashboard" layoutMode="focus">
      <div className={`workspace-shell ${showConsole ? "workspace-shell--with-console" : ""}`}>
        <section className="chat-surface">
          <header className="chat-surface__header">
            <div>
              <p className="eyebrow">Sessão ativa</p>
              <h2>Chat focado na execução</h2>
              <p className="subtitle">
                Uma interface mais limpa para conversar com os agentes sem o visual de dashboard.
              </p>
            </div>

            <div className="chat-surface__actions">
              <button className="secondary-button" type="button" onClick={handleCreateSession}>
                Nova sessão
              </button>
              <button
                className="secondary-button"
                type="button"
                onClick={() => setIsConsoleOpen((current) => !current)}
              >
                {showConsole ? "Ocultar painel" : "Abrir painel"}
              </button>
              <button
                type="button"
                onClick={handleExecutePlan}
                disabled={!executionPlan || executionPlan.tasks.length === 0 || isExecutingPlan}
              >
                {isExecutingPlan ? "Executando..." : "Executar plano"}
              </button>
            </div>
          </header>

          <div className="chat-overview">
            <div className="chat-overview__meta">
              <span className="status-pill">{executionStatus}</span>
              <span className="tag">{currentWorkspaceLabel || "Workspace não configurado"}</span>
              <span className="tag">Sessões: {sessions.length}</span>
            </div>
            <p className="run-card__meta">
              Sessão: {sessionId || "não iniciada"} · Root: {currentProjectRoot || "não configurado"}
            </p>
            {executionPlan ? (
              <div className="plan-preview">
                <div className="plan-preview__header">
                  <strong>Próximas etapas</strong>
                  <span className="run-card__meta">{executionPlan.tasks.length} tarefas</span>
                </div>
                {nextTasks.length === 0 ? (
                  <p className="empty-state">
                    Envie uma instrução no chat para gerar um backlog executável.
                  </p>
                ) : (
                  <ol className="plan-preview__list">
                    {nextTasks.map((task) => (
                      <li key={task.task_id}>
                        <strong>{task.title}</strong>
                        <span>{task.description}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            ) : null}
          </div>

          {error ? <p className="error-banner">{error}</p> : null}

          <MessageList messages={messages} />

          <form className="chat-composer chat-composer--clean" onSubmit={handleSubmit}>
            <textarea
              value={pendingMessage}
              onChange={(event) => setPendingMessage(event.target.value)}
              placeholder="Descreva a mudança que você quer fazer..."
            />
            <button type="submit" disabled={isLoading || !pendingMessage.trim()}>
              {isLoading ? "Enviando..." : "Enviar"}
            </button>
          </form>

          <div className="chat-plan-notes">
            <strong>Plano atual</strong>
            <div className="tag-list">
              {plan.map((step, index) => (
                <span className="tag" key={`${index}-${step}`}>
                  {step}
                </span>
              ))}
            </div>
          </div>
        </section>

        {showConsole ? <ExecutionConsolePanel runs={runs} isBusy={isBusy} /> : null}
      </div>
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
