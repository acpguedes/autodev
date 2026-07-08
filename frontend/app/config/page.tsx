"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import PlanSidebar from "../../components/PlanSidebar";
import { useShellHeader } from "@/components/shell/ShellProvider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  type RepositoryContextResponse,
  type RuntimeConfig,
  type RuntimeInstructions,
  type SessionResponse,
  getRepositoryContext,
  getRuntimeConfig,
  listSessions,
  updateRuntimeConfig,
} from "../../lib/api";

const DEFAULT_REPOSITORY_QUERY = "configuração llm repositório projeto";

const kickerClass = "text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3";
const fieldLabel = "text-sm font-medium text-ds-fg-2";
const selectClass =
  "flex h-9 w-full rounded-md border border-ds-line bg-ds-bg-2 px-3 py-1 text-sm text-ds-fg shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ds-accent";
const textareaClass =
  "min-h-[110px] w-full resize-y rounded-ds-md border border-ds-line bg-ds-bg-2 px-3 py-2 text-sm text-ds-fg shadow-sm transition-colors placeholder:text-ds-fg-3 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ds-accent";
const codeBlockClass =
  "overflow-x-auto whitespace-pre-wrap rounded-ds-md border border-ds-line bg-ds-bg-3 p-4 font-mono text-[13px] text-ds-fg-2";

export default function ConfigPage() {
  useShellHeader({
    title: "Config",
    subtitle: "Repository and model settings.",
  });

  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [configDraft, setConfigDraft] = useState<RuntimeConfig | null>(null);
  const [instructions, setInstructions] = useState<RuntimeInstructions | null>(null);
  const [configStatus, setConfigStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionResponse[]>([]);
  const [repositoryContext, setRepositoryContext] =
    useState<RepositoryContextResponse | null>(null);
  const [repositoryQuery, setRepositoryQuery] = useState(DEFAULT_REPOSITORY_QUERY);

  useEffect(() => {
    async function bootstrap() {
      try {
        const runtime = await getRuntimeConfig();
        setConfig(runtime.config);
        setConfigDraft(runtime.config);
        setInstructions(runtime.instructions);
        const existingSessions = await listSessions();
        setSessions(existingSessions);
        setRepositoryContext(await getRepositoryContext(DEFAULT_REPOSITORY_QUERY));
      } catch {
        setError("Failed to load configuration workspace.");
      }
    }

    void bootstrap();
  }, []);

  const activeSession = sessions[0];
  const canSaveConfig = useMemo(() => {
    if (!configDraft) {
      return false;
    }

    return Boolean(
      configDraft.repository.project_root.trim() &&
        configDraft.repository.default_goal.trim() &&
        configDraft.llm.provider.trim()
    );
  }, [configDraft]);

  async function handleSaveConfiguration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!configDraft) {
      return;
    }

    setConfigStatus("Saving configuration...");
    setError(null);

    try {
      const response = await updateRuntimeConfig(configDraft);
      setConfig(response.config);
      setConfigDraft(response.config);
      setInstructions(response.instructions);
      setRepositoryContext(await getRepositoryContext(repositoryQuery || DEFAULT_REPOSITORY_QUERY));
      setSessions(await listSessions());
      setConfigStatus("Configuration saved to the runtime config file.");
    } catch {
      setConfigStatus(null);
      setError("Unable to save runtime configuration.");
    }
  }

  async function handleRepositorySearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    try {
      setRepositoryContext(await getRepositoryContext(repositoryQuery || DEFAULT_REPOSITORY_QUERY));
    } catch {
      setError("Unable to load repository context for the configured project.");
    }
  }

  return (
    <div className="flex flex-col gap-6 p-8">
      <PlanSidebar
        plan={activeSession?.plan ?? []}
        sessionId={activeSession?.session_id}
        status={activeSession?.status ?? "idle"}
        repositoryLabel={
          configDraft?.repository.repository_label || config?.repository.repository_label
        }
        projectRoot={configDraft?.repository.project_root || config?.repository.project_root}
      />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <p className={kickerClass}>Configuration workspace</p>
          <h1 className="font-serif text-2xl font-semibold text-ds-fg">
            Repository + model settings
          </h1>
          <p className="max-w-2xl text-sm text-ds-fg-3">
            Move runtime configuration into a dedicated area while keeping repository context and
            environment instructions close to the active workspace.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/">Back to dashboard</Link>
        </Button>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
          <CardHeader className="flex-row items-start justify-between space-y-0 gap-3">
            <div className="flex flex-col gap-1">
              <p className={kickerClass}>Runtime configuration</p>
              <h2 className="font-serif text-lg font-semibold text-ds-fg">
                LLM + repository setup
              </h2>
            </div>
            {configStatus ? <p className="text-sm text-ds-fg-3">{configStatus}</p> : null}
          </CardHeader>
          <CardContent>
            {configDraft ? (
              <form className="flex flex-col gap-4" onSubmit={handleSaveConfiguration}>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="flex flex-col gap-1.5">
                    <span className={fieldLabel}>LLM provider</span>
                    <select
                      className={selectClass}
                      value={configDraft.llm.provider}
                      onChange={(event) =>
                        setConfigDraft({
                          ...configDraft,
                          llm: { ...configDraft.llm, provider: event.target.value },
                        })
                      }
                    >
                      <option value="stub">stub</option>
                      <option value="openai">openai</option>
                      <option value="ollama">ollama</option>
                    </select>
                  </label>

                  <label className="flex flex-col gap-1.5">
                    <span className={fieldLabel}>Model</span>
                    <Input
                      value={configDraft.llm.model}
                      onChange={(event) =>
                        setConfigDraft({
                          ...configDraft,
                          llm: { ...configDraft.llm, model: event.target.value },
                        })
                      }
                    />
                  </label>

                  <label className="flex flex-col gap-1.5">
                    <span className={fieldLabel}>Base URL</span>
                    <Input
                      value={configDraft.llm.base_url}
                      placeholder="OpenAI-compatible gateway or Ollama /v1 endpoint"
                      onChange={(event) =>
                        setConfigDraft({
                          ...configDraft,
                          llm: { ...configDraft.llm, base_url: event.target.value },
                        })
                      }
                    />
                  </label>

                  <label className="flex flex-col gap-1.5">
                    <span className={fieldLabel}>Temperature</span>
                    <Input
                      type="number"
                      min="0"
                      max="2"
                      step="0.1"
                      value={configDraft.llm.temperature}
                      onChange={(event) =>
                        setConfigDraft({
                          ...configDraft,
                          llm: {
                            ...configDraft.llm,
                            temperature: Number(event.target.value || 0),
                          },
                        })
                      }
                    />
                  </label>

                  <label className="flex flex-col gap-1.5 sm:col-span-2">
                    <span className={fieldLabel}>API key</span>
                    <Input
                      type="password"
                      value={configDraft.llm.api_key}
                      placeholder="Optional for stub mode"
                      onChange={(event) =>
                        setConfigDraft({
                          ...configDraft,
                          llm: { ...configDraft.llm, api_key: event.target.value },
                        })
                      }
                    />
                  </label>

                  <label className="flex flex-col gap-1.5">
                    <span className={fieldLabel}>Repository label</span>
                    <Input
                      value={configDraft.repository.repository_label}
                      onChange={(event) =>
                        setConfigDraft({
                          ...configDraft,
                          repository: {
                            ...configDraft.repository,
                            repository_label: event.target.value,
                          },
                        })
                      }
                    />
                  </label>

                  <label className="flex flex-col gap-1.5">
                    <span className={fieldLabel}>Project root</span>
                    <Input
                      value={configDraft.repository.project_root}
                      onChange={(event) =>
                        setConfigDraft({
                          ...configDraft,
                          repository: {
                            ...configDraft.repository,
                            project_root: event.target.value,
                          },
                        })
                      }
                    />
                  </label>

                  <label className="flex flex-col gap-1.5 sm:col-span-2">
                    <span className={fieldLabel}>Default planning goal</span>
                    <textarea
                      className={textareaClass}
                      value={configDraft.repository.default_goal}
                      onChange={(event) =>
                        setConfigDraft({
                          ...configDraft,
                          repository: {
                            ...configDraft.repository,
                            default_goal: event.target.value,
                          },
                        })
                      }
                    />
                  </label>
                </div>

                <div className="flex justify-end">
                  <Button type="submit" disabled={!canSaveConfig}>
                    Save configuration
                  </Button>
                </div>
              </form>
            ) : (
              <p className="text-sm text-ds-fg-3">Loading configuration...</p>
            )}
          </CardContent>
        </Card>

        <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
          <CardHeader>
            <p className={kickerClass}>Config as file</p>
            <h2 className="font-serif text-lg font-semibold text-ds-fg">
              File and environment instructions
            </h2>
          </CardHeader>
          <CardContent>
            {instructions ? (
              <div className="flex flex-col gap-4">
                <div>
                  <p className={`${fieldLabel} mb-1`}>Config file path</p>
                  <code className="rounded-ds-sm bg-ds-bg-3 px-1.5 py-0.5 font-mono text-[13px] text-ds-fg-2">
                    {instructions.config_path}
                  </code>
                </div>

                <div>
                  <p className={`${fieldLabel} mb-1`}>JSON config example</p>
                  <pre className={codeBlockClass}>{instructions.config_file_example}</pre>
                </div>

                <div>
                  <p className={`${fieldLabel} mb-1`}>.env example</p>
                  <pre className={codeBlockClass}>{instructions.env_file_example}</pre>
                </div>

                <ul className="list-disc pl-5 text-sm text-ds-fg-2 marker:text-ds-fg-3">
                  {instructions.notes.map((note) => (
                    <li className="mb-1 last:mb-0" key={note}>
                      {note}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="text-sm text-ds-fg-3">Loading instructions...</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
        <CardHeader>
          <p className={kickerClass}>Repository intelligence</p>
          <h2 className="font-serif text-lg font-semibold text-ds-fg">
            Context preview for the active project
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form className="flex flex-wrap items-center gap-3" onSubmit={handleRepositorySearch}>
            <Input
              className="min-w-[240px] flex-1"
              value={repositoryQuery}
              onChange={(event) => setRepositoryQuery(event.target.value)}
              placeholder="Search the configured repository context"
            />
            <Button type="submit" variant="outline">
              Refresh context
            </Button>
          </form>

          {repositoryContext ? (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-ds-fg-3">
                Root: {repositoryContext.root} · Files: {repositoryContext.total_files}
              </p>
              <div className="flex flex-wrap gap-2">
                {repositoryContext.top_directories.map((directory) => (
                  <Badge variant="outline" className="text-ds-fg-2" key={directory}>
                    {directory}
                  </Badge>
                ))}
              </div>
              <div className="flex flex-col gap-3">
                {repositoryContext.candidate_files.map((file) => (
                  <article
                    className="flex flex-col gap-1 rounded-ds-md border border-ds-line bg-ds-bg-3 p-3"
                    key={file.path}
                  >
                    <strong className="font-mono text-[13px] text-ds-fg">{file.path}</strong>
                    <p className="text-xs text-ds-fg-3">score {file.score}</p>
                    <p className="text-xs text-ds-fg-3">{file.reasons.join(" · ")}</p>
                  </article>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-ds-fg-3">Loading repository context...</p>
          )}
        </CardContent>
      </Card>

      {error ? (
        <p
          role="alert"
          className="rounded-ds-md border border-ds-danger/40 bg-ds-danger/10 px-4 py-3 text-sm text-ds-danger"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}
