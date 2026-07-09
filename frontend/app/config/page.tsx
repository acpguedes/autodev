"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { ProviderSelector, defaultModelFor, type ProviderId } from "@/components/ProviderSelector";
import { useShellHeader } from "@/components/shell/ShellProvider";
import { StatusGlowDot } from "@/components/StatusGlowDot";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  getProviderStatusV2,
  getRuntimeConfigV2,
  updateRuntimeConfigV2,
  type ProviderStatusV2,
  type RuntimeConfigV2,
  type RuntimeInstructionsV2,
} from "@/lib/api_v2";
import { toast } from "@/lib/use-toast";

const kickerClass = "text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3";
const fieldLabel = "text-sm font-medium text-ds-fg-2";
const textareaClass =
  "min-h-[110px] w-full resize-y rounded-ds-md border border-ds-line bg-ds-bg-2 px-3 py-2 text-sm text-ds-fg shadow-sm transition-colors placeholder:text-ds-fg-3 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ds-accent";
const codeBlockClass =
  "overflow-x-auto whitespace-pre-wrap rounded-ds-md border border-ds-line bg-ds-bg-3 p-4 font-mono text-[13px] text-ds-fg-2";

/**
 * Validate a configuration draft before it is submitted for save.
 *
 * Requires a non-empty provider, model, and project root, and (when a base
 * URL is supplied) that it parses as an absolute URL — providers such as
 * the offline stub may legitimately leave it blank.
 *
 * @param draft - The in-progress configuration draft.
 * @returns The first validation error found, or `null` if the draft is valid.
 */
function validateConfigDraft(draft: RuntimeConfigV2): string | null {
  if (!draft.llm.provider.trim()) {
    return "Choose an LLM provider.";
  }
  if (!draft.llm.model.trim()) {
    return "Model name is required.";
  }
  if (!draft.repository.project_root.trim()) {
    return "Project directory is required.";
  }
  if (!draft.repository.default_goal.trim()) {
    return "Default goal is required.";
  }
  const baseUrl = draft.llm.base_url.trim();
  if (baseUrl) {
    try {
      // eslint-disable-next-line no-new -- validation only, result unused.
      new URL(baseUrl);
    } catch {
      return "Base URL must be a valid absolute URL.";
    }
  }
  return null;
}

/**
 * Configuration screen: selects the active LLM provider, model, base URL,
 * project directory, and default goal, wired to the E16 runtime-config and
 * provider-status endpoints with client-side validation and optimistic save
 * feedback.
 *
 * @returns The configuration page.
 */
export default function ConfigPage() {
  useShellHeader({
    title: "Config",
    subtitle: "Provider and repository settings.",
  });

  const [config, setConfig] = useState<RuntimeConfigV2 | null>(null);
  const [configDraft, setConfigDraft] = useState<RuntimeConfigV2 | null>(null);
  const [instructions, setInstructions] = useState<RuntimeInstructionsV2 | null>(null);
  const [providerStatus, setProviderStatus] = useState<ProviderStatusV2 | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    async function bootstrap() {
      try {
        const runtime = await getRuntimeConfigV2();
        setConfig(runtime.config);
        setConfigDraft(runtime.config);
        setInstructions(runtime.instructions);
      } catch {
        setError("Failed to load configuration.");
      }
      try {
        setProviderStatus(await getProviderStatusV2());
      } catch {
        setProviderStatus(null);
      }
    }

    void bootstrap();
  }, []);

  const canSaveConfig = useMemo(() => {
    if (!configDraft) {
      return false;
    }
    return validateConfigDraft(configDraft) === null;
  }, [configDraft]);

  function handleProviderChange(providerId: ProviderId) {
    if (!configDraft) {
      return;
    }
    const nextModel = defaultModelFor(providerId) ?? configDraft.llm.model;
    setConfigDraft({
      ...configDraft,
      llm: { ...configDraft.llm, provider: providerId, model: nextModel },
    });
  }

  async function handleSaveConfiguration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!configDraft) {
      return;
    }

    const validation = validateConfigDraft(configDraft);
    if (validation) {
      setValidationError(validation);
      return;
    }
    setValidationError(null);

    // Optimistic update: apply the draft immediately, then reconcile with the
    // server response (or roll back on failure).
    const previousConfig = config;
    setConfig(configDraft);
    setSaving(true);
    setError(null);

    try {
      const response = await updateRuntimeConfigV2(configDraft);
      setConfig(response.config);
      setConfigDraft(response.config);
      setInstructions(response.instructions);
      toast({ title: "Configuration saved", description: "Runtime config updated." });
      try {
        setProviderStatus(await getProviderStatusV2());
      } catch {
        setProviderStatus(null);
      }
    } catch {
      setConfig(previousConfig);
      setError("Unable to save runtime configuration.");
      toast({
        title: "Could not save configuration",
        description: "The control plane rejected the request or is unavailable.",
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-6 p-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <p className={kickerClass}>Configuration</p>
          <h1 className="font-serif text-2xl font-semibold text-ds-fg">
            Provider + repository settings
          </h1>
          <p className="max-w-2xl text-sm text-ds-fg-3">
            Choose the LLM provider, model, and project workspace used for new sessions.
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
                Provider + repository setup
              </h2>
            </div>
            {providerStatus ? (
              <StatusGlowDot
                tone={providerStatus.healthy ? "success" : providerStatus.configured ? "warn" : "danger"}
                label={
                  providerStatus.healthy
                    ? `${providerStatus.name} healthy`
                    : providerStatus.configured
                      ? `${providerStatus.name} not verified`
                      : `${providerStatus.name} not configured`
                }
              />
            ) : null}
          </CardHeader>
          <CardContent>
            {configDraft ? (
              <form className="flex flex-col gap-4" onSubmit={handleSaveConfiguration}>
                <div className="flex flex-col gap-1.5">
                  <span className={fieldLabel}>LLM provider</span>
                  <ProviderSelector
                    value={configDraft.llm.provider}
                    onChange={handleProviderChange}
                    disabled={saving}
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
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

                  <label className="flex flex-col gap-1.5">
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
                    <span className={fieldLabel}>Project directory</span>
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
                    <span className={fieldLabel}>Default goal</span>
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

                {validationError ? (
                  <p role="alert" className="text-sm text-ds-danger">
                    {validationError}
                  </p>
                ) : null}

                <div className="flex justify-end">
                  <Button type="submit" disabled={!canSaveConfig || saving}>
                    {saving ? "Saving…" : "Save configuration"}
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
