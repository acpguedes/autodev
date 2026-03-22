"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import ChatLayout from "../../components/ChatLayout";
import PlanSidebar from "../../components/PlanSidebar";
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

export default function ConfigPage() {
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
    <ChatLayout
      currentView="config"
      sidebar={
        <PlanSidebar
          plan={activeSession?.plan ?? []}
          sessionId={activeSession?.session_id}
          status={activeSession?.status ?? "idle"}
          repositoryLabel={
            configDraft?.repository.repository_label || config?.repository.repository_label
          }
          projectRoot={configDraft?.repository.project_root || config?.repository.project_root}
        />
      }
    >
      <section className="hero-card">
        <div>
          <p className="eyebrow">Configuration workspace</p>
          <h1>Repository + model settings</h1>
          <p className="subtitle">
            Move runtime configuration into a dedicated area while keeping repository context and
            environment instructions close to the active workspace.
          </p>
        </div>
        <div className="hero-card__actions">
          <Link className="secondary-button secondary-button--link" href="/">
            Back to dashboard
          </Link>
        </div>
      </section>

      <div className="panel-grid panel-grid--two-up">
        <section className="panel-card">
          <div className="panel-card__header">
            <div>
              <p className="eyebrow">Runtime configuration</p>
              <h2>LLM + repository setup</h2>
            </div>
            {configStatus ? <p className="status-text">{configStatus}</p> : null}
          </div>

          {configDraft ? (
            <form className="config-form" onSubmit={handleSaveConfiguration}>
              <div className="config-form__grid">
                <label>
                  <span>LLM provider</span>
                  <select
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
                  </select>
                </label>

                <label>
                  <span>Model</span>
                  <input
                    value={configDraft.llm.model}
                    onChange={(event) =>
                      setConfigDraft({
                        ...configDraft,
                        llm: { ...configDraft.llm, model: event.target.value },
                      })
                    }
                  />
                </label>

                <label>
                  <span>Base URL</span>
                  <input
                    value={configDraft.llm.base_url}
                    placeholder="Optional proxy / OpenAI-compatible gateway"
                    onChange={(event) =>
                      setConfigDraft({
                        ...configDraft,
                        llm: { ...configDraft.llm, base_url: event.target.value },
                      })
                    }
                  />
                </label>

                <label>
                  <span>Temperature</span>
                  <input
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

                <label className="config-form__full-width">
                  <span>API key</span>
                  <input
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

                <label>
                  <span>Repository label</span>
                  <input
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

                <label>
                  <span>Project root</span>
                  <input
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

                <label className="config-form__full-width">
                  <span>Default planning goal</span>
                  <textarea
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

              <div className="config-form__actions">
                <button type="submit" disabled={!canSaveConfig}>
                  Save configuration
                </button>
              </div>
            </form>
          ) : (
            <p className="empty-state">Loading configuration...</p>
          )}
        </section>

        <section className="panel-card">
          <div className="panel-card__header">
            <div>
              <p className="eyebrow">Config as file</p>
              <h2>File and environment instructions</h2>
            </div>
          </div>

          {instructions ? (
            <div className="instruction-stack">
              <div>
                <p className="info-label">Config file path</p>
                <code className="inline-code">{instructions.config_path}</code>
              </div>

              <div>
                <p className="info-label">JSON config example</p>
                <pre className="code-block">{instructions.config_file_example}</pre>
              </div>

              <div>
                <p className="info-label">.env example</p>
                <pre className="code-block">{instructions.env_file_example}</pre>
              </div>

              <ul className="note-list">
                {instructions.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="empty-state">Loading instructions...</p>
          )}
        </section>
      </div>

      <section className="panel-card">
        <div className="panel-card__header">
          <div>
            <p className="eyebrow">Repository intelligence</p>
            <h2>Context preview for the active project</h2>
          </div>
        </div>

        <form className="search-form" onSubmit={handleRepositorySearch}>
          <input
            value={repositoryQuery}
            onChange={(event) => setRepositoryQuery(event.target.value)}
            placeholder="Search the configured repository context"
          />
          <button type="submit">Refresh context</button>
        </form>

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

      {error ? (
        <p role="alert" className="error-banner">
          {error}
        </p>
      ) : null}
    </ChatLayout>
  );
}
