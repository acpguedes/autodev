"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { toast } from "@/lib/use-toast";
import {
  getAgentExtensionV2,
  upsertAgentExtensionV2,
  type AgentUpsertPayloadV2,
} from "@/lib/api_v2";

const fieldLabel = "text-sm font-medium text-ds-fg-2";
const textareaClass =
  "min-h-[110px] w-full resize-y rounded-ds-md border border-ds-line bg-ds-bg-2 px-3 py-2 text-sm text-ds-fg shadow-sm transition-colors placeholder:text-ds-fg-3 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ds-accent";

/** Editable draft state backing the agent create/edit form. */
type AgentDraft = {
  agentId: string;
  displayName: string;
  version: string;
  model: string;
  allowedTools: string;
  systemPrompt: string;
};

const EMPTY_DRAFT: AgentDraft = {
  agentId: "",
  displayName: "",
  version: "",
  model: "",
  allowedTools: "",
  systemPrompt: "",
};

/** Props accepted by {@link AgentFormDialog}. */
export interface AgentFormDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Called when the dialog should open or close. */
  onOpenChange: (open: boolean) => void;
  /**
   * Identifier of the agent being edited. Omit (or pass `null`) to open the
   * dialog in "create a new agent" mode, which asks for the agent id too.
   */
  agentId?: string | null;
  /** Called after a successful create/edit, so the caller can revalidate the catalog. */
  onSaved: () => void;
}

/**
 * Modal form for creating or editing an agent extension, wired to
 * `GET`/`PUT /v2/extensions/agents/{agentId}` (E16-S4). Agents are the only
 * extension kind with a real edit endpoint — the system prompt, model, and
 * allowed tools captured here map directly onto the conceptual versioned
 * `agent.yaml` manifest.
 *
 * @param props - See {@link AgentFormDialogProps}.
 * @returns The rendered dialog.
 */
export function AgentFormDialog({
  open,
  onOpenChange,
  agentId = null,
  onSaved,
}: AgentFormDialogProps): React.JSX.Element {
  const isEdit = Boolean(agentId);
  const [draft, setDraft] = React.useState<AgentDraft>(EMPTY_DRAFT);
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) {
      return;
    }
    setError(null);
    if (!agentId) {
      setDraft(EMPTY_DRAFT);
      return;
    }
    let cancelled = false;
    setLoading(true);
    getAgentExtensionV2(agentId)
      .then((detail) => {
        if (cancelled) return;
        // The catalog/detail endpoints stamp the manifest's version into
        // `item.detail.version` (see `_agent_item` in
        // `backend/api/routers/extensions_v2.py`). Carrying it into the
        // draft — instead of leaving it blank — is required so a save that
        // doesn't touch this field updates the agent's existing version
        // rather than upserting a new, lower-versioned row (the backend
        // defaults an omitted `version` to "1.0.0" and resolves "latest" by
        // highest SemVer, so an unpopulated field can silently orphan edits).
        const existingVersion = detail.item.detail?.version;
        setDraft({
          agentId,
          displayName: detail.item.name ?? "",
          version: typeof existingVersion === "string" ? existingVersion : "",
          model: detail.model ?? "",
          allowedTools: detail.allowedTools?.join(", ") ?? "",
          systemPrompt: detail.systemPrompt ?? "",
        });
      })
      .catch(() => {
        if (!cancelled) {
          setError("Failed to load this agent's manifest.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, agentId]);

  const canSave =
    draft.agentId.trim().length > 0 &&
    draft.model.trim().length > 0 &&
    draft.systemPrompt.trim().length > 0 &&
    !saving &&
    !loading;

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!canSave) {
      return;
    }
    setSaving(true);
    setError(null);
    const payload: AgentUpsertPayloadV2 = {
      systemPrompt: draft.systemPrompt.trim(),
      model: draft.model.trim(),
      allowedTools: draft.allowedTools
        .split(",")
        .map((tool) => tool.trim())
        .filter((tool) => tool.length > 0),
    };
    if (draft.displayName.trim()) payload.displayName = draft.displayName.trim();
    if (draft.version.trim()) payload.version = draft.version.trim();

    try {
      await upsertAgentExtensionV2(draft.agentId.trim(), payload);
      toast({
        title: isEdit ? "Agent updated" : "Agent created",
        description: draft.agentId.trim(),
      });
      onSaved();
      onOpenChange(false);
    } catch {
      setError("Unable to save this agent. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl bg-ds-bg-2 text-ds-fg">
        <DialogHeader>
          <DialogTitle className="font-serif">
            {isEdit ? "Edit agent" : "Create agent"}
          </DialogTitle>
          <DialogDescription className="text-ds-fg-2">
            {isEdit
              ? "Update this agent's instruction, model, and allowed tools."
              : "Register a new agent manifest (agent.yaml)."}
          </DialogDescription>
        </DialogHeader>

        <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className={fieldLabel}>Agent id</span>
              <Input
                value={draft.agentId}
                disabled={isEdit || loading}
                placeholder="namespace/agent-name"
                onChange={(event) => setDraft((d) => ({ ...d, agentId: event.target.value }))}
                required
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className={fieldLabel}>Display name</span>
              <Input
                value={draft.displayName}
                disabled={loading}
                placeholder="Optional"
                onChange={(event) => setDraft((d) => ({ ...d, displayName: event.target.value }))}
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className={fieldLabel}>Model</span>
              <Input
                value={draft.model}
                disabled={loading}
                placeholder="e.g. claude-sonnet-5"
                onChange={(event) => setDraft((d) => ({ ...d, model: event.target.value }))}
                required
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className={fieldLabel}>Version</span>
              <Input
                value={draft.version}
                disabled={loading}
                placeholder="Optional, e.g. 1.0.0"
                onChange={(event) => setDraft((d) => ({ ...d, version: event.target.value }))}
              />
            </label>

            <label className="flex flex-col gap-1.5 sm:col-span-2">
              <span className={fieldLabel}>Allowed tools</span>
              <Input
                value={draft.allowedTools}
                disabled={loading}
                placeholder="Comma-separated, e.g. read_file, write_file, run_tests"
                onChange={(event) => setDraft((d) => ({ ...d, allowedTools: event.target.value }))}
              />
            </label>

            <label className="flex flex-col gap-1.5 sm:col-span-2">
              <span className={fieldLabel}>Agent instruction (system prompt)</span>
              <textarea
                className={textareaClass}
                value={draft.systemPrompt}
                disabled={loading}
                placeholder="You are a specialized agent that..."
                onChange={(event) => setDraft((d) => ({ ...d, systemPrompt: event.target.value }))}
                required
              />
            </label>
          </div>

          {error ? (
            <p
              role="alert"
              className="rounded-ds-md border border-ds-danger/40 bg-ds-danger/10 px-3 py-2 text-sm text-ds-danger"
            >
              {error}
            </p>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSave}>
              {saving ? "Saving..." : isEdit ? "Save changes" : "Create agent"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
