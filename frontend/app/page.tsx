"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import ExecutionConsolePanel from "../components/ExecutionConsolePanel";
import MessageList, { type Message } from "../components/MessageList";
import { useExecutionPanel, useShell, useShellHeader } from "@/components/shell/ShellProvider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useTranslations } from "@/lib/i18n";
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

const textareaClass =
  "min-h-[110px] w-full resize-y rounded-ds-md border border-ds-line bg-ds-bg-2 px-3 py-2 text-sm text-ds-fg shadow-sm transition-colors placeholder:text-ds-fg-3 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ds-accent";

export default function Page() {
  return <ExecutionControlCenter />;
}

function ExecutionControlCenter() {
  const { t } = useTranslations();
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
  const { setPanelOpen } = useShell();

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
              content: t("chat.initialPlanMessage", { goal: planResponse.goal }),
            },
          ]);
          setSessions(await listSessions());
          setExecutionPlan(await getExecutionPlan(planResponse.session_id));
        }
      } catch {
        setError(t("chat.errors.loadWorkspace"));
      }
    }

    void bootstrap();
    // Only ever bootstrap once on mount; `t` is stable per locale and
    // re-running this on locale change would re-fetch session state for no
    // reason.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentWorkspaceLabel = config?.repository.repository_label;
  const currentProjectRoot = config?.repository.project_root;
  const executionStatus = runs[0]?.status ?? executionPlan?.status ?? "awaiting_input";
  const isBusy = isLoading || isExecutingPlan;
  const hasConsoleEntries = runs.some((run) => run.results.length > 0);
  const nextTasks = executionPlan?.tasks.slice(0, 3) ?? [];

  // Surface the execution console in the shell's right panel and auto-open it
  // whenever there is live activity or recorded output to show.
  const consoleContent = useMemo(
    () => <ExecutionConsolePanel runs={runs} isBusy={isBusy} />,
    [runs, isBusy]
  );
  useExecutionPanel(consoleContent);

  useEffect(() => {
    if (isBusy || hasConsoleEntries) {
      setPanelOpen(true);
    }
  }, [hasConsoleEntries, isBusy, setPanelOpen]);

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
      setError(t("chat.errors.sendMessage"));
    } finally {
      setPendingMessage("");
      setIsLoading(false);
    }
  }

  const handleCreateSession = useCallback(async () => {
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
          content: t("chat.initialPlanMessage", { goal: response.goal }),
        },
      ]);
      setSessions(await listSessions());
      setExecutionPlan(await getExecutionPlan(response.session_id));
      setPanelOpen(false);
    } catch {
      setError(t("chat.errors.createSession"));
    }
    // `t` is stable per locale; omitting it keeps this callback's identity
    // tied to the values that actually change its behavior.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config, setPanelOpen]);

  useShellHeader({
    title: t("chat.pageTitle"),
    subtitle: t("chat.pageSubtitle"),
    onNewSession: handleCreateSession,
  });

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
      setError(t("chat.errors.executePlan"));
    } finally {
      setIsExecutingPlan(false);
    }
  }

  return (
    <div className="flex flex-col gap-6 p-8">
      <section className="flex flex-col gap-5 rounded-lg border border-ds-line bg-ds-bg-2 p-6 shadow-ds-sm">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">
              {t("chat.sessionLabel")}
            </p>
            <h2 className="font-serif text-xl font-semibold text-ds-fg">
              {t("chat.heading")}
            </h2>
            <p className="text-sm text-ds-fg-3">
              {t("chat.description")}
            </p>
          </div>

          <Button
            type="button"
            onClick={handleExecutePlan}
            disabled={!executionPlan || executionPlan.tasks.length === 0 || isExecutingPlan}
          >
            {isExecutingPlan ? t("chat.executingPlan") : t("chat.executePlan")}
          </Button>
        </header>

        <div className="flex flex-col gap-3 rounded-ds-md border border-ds-line bg-ds-bg-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{executionStatus}</Badge>
            <Badge variant="outline" className="text-ds-fg-2">
              {currentWorkspaceLabel || t("chat.workspaceUnconfigured")}
            </Badge>
            <Badge variant="outline" className="text-ds-fg-2">
              {t("chat.sessionsCount", { count: sessions.length })}
            </Badge>
          </div>
          <p className="text-xs text-ds-fg-3">
            {t("chat.sessionMeta", {
              sessionId: sessionId || t("chat.sessionNotStarted"),
              projectRoot: currentProjectRoot || t("chat.rootNotConfigured"),
            })}
          </p>
          {executionPlan ? (
            <div className="flex flex-col gap-2 rounded-ds-md border border-ds-line bg-ds-bg-2 p-3">
              <div className="flex items-center justify-between gap-2">
                <strong className="text-sm font-semibold text-ds-fg">
                  {t("chat.nextSteps")}
                </strong>
                <span className="text-xs text-ds-fg-3">
                  {t("chat.taskCount", { count: executionPlan.tasks.length })}
                </span>
              </div>
              {nextTasks.length === 0 ? (
                <p className="text-sm text-ds-fg-3">
                  {t("chat.noTasksPrompt")}
                </p>
              ) : (
                <ol className="list-decimal flex-col gap-2 pl-5 text-sm text-ds-fg-2 marker:text-ds-fg-3">
                  {nextTasks.map((task) => (
                    <li key={task.task_id} className="mb-2 last:mb-0">
                      <strong className="block text-ds-fg">{task.title}</strong>
                      <span>{task.description}</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          ) : null}
        </div>

        {error ? (
          <p
            role="alert"
            className="rounded-ds-md border border-ds-danger/40 bg-ds-danger/10 px-4 py-3 text-sm text-ds-danger"
          >
            {error}
          </p>
        ) : null}

        <MessageList messages={messages} />

        <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
          <textarea
            className={textareaClass}
            value={pendingMessage}
            onChange={(event) => setPendingMessage(event.target.value)}
            placeholder={t("chat.messagePlaceholder")}
          />
          <div className="flex justify-end">
            <Button type="submit" disabled={isLoading || !pendingMessage.trim()}>
              {isLoading ? t("chat.sending") : t("chat.send")}
            </Button>
          </div>
        </form>

        <div className="flex flex-col gap-2">
          <strong className="text-sm font-semibold text-ds-fg">
            {t("chat.currentPlan")}
          </strong>
          <div className="flex flex-wrap gap-2">
            {plan.map((step, index) => (
              <Badge variant="outline" className="text-ds-fg-2" key={`${index}-${step}`}>
                {step}
              </Badge>
            ))}
          </div>
        </div>
      </section>
    </div>
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
