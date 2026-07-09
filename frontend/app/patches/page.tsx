"use client";

// Patches review screen (E17-S3): left file panel + right Diff/Edit
// segmented viewer for the E16-S3 patch review lifecycle. Talks only to
// `/v2` endpoints via `lib/api_patches_v2.ts` and `lib/api_v2.ts`, per the
// API-first rule (docs/architecture/v2_platform_reference.md §2.13).

import * as React from "react";

import { PatchFileList } from "@/components/patches/PatchFileList";
import {
  PatchSegmentedViewer,
  type PatchViewerMode,
} from "@/components/patches/PatchSegmentedViewer";
import { useShellHeader } from "@/components/shell/ShellProvider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  applyPatchV2,
  discardPatchV2,
  getPatchDiffV2,
  listChangedFilesV2,
  overridePatchContentV2,
  type ChangedFileV2,
  type PatchDetailV2,
} from "@/lib/api_patches_v2";
import { listSessionsV2, type SessionV2 } from "@/lib/api_v2";
import { toast } from "@/lib/use-toast";

export default function PatchesPage() {
  useShellHeader({
    title: "Patch review",
    subtitle: "Unified diff in dry-run · nothing is written without approval.",
  });

  const [sessions, setSessions] = React.useState<SessionV2[] | null>(null);
  const [sessionsError, setSessionsError] = React.useState<string | null>(null);
  const [sessionId, setSessionId] = React.useState<string | null>(null);

  const [files, setFiles] = React.useState<ChangedFileV2[] | null>(null);
  const [filesError, setFilesError] = React.useState<string | null>(null);
  const [patchId, setPatchId] = React.useState<string | null>(null);

  const [patch, setPatch] = React.useState<PatchDetailV2 | null>(null);
  const [patchError, setPatchError] = React.useState<string | null>(null);
  const [mode, setMode] = React.useState<PatchViewerMode>("diff");
  const [editValue, setEditValue] = React.useState("");
  const [actionBusy, setActionBusy] = React.useState(false);

  const loadSessions = React.useCallback(async () => {
    try {
      const list = await listSessionsV2();
      setSessions(list.items);
      setSessionsError(null);
      setSessionId((current) => current ?? list.items[0]?.session_id ?? null);
    } catch {
      setSessions([]);
      setSessionsError("Could not load sessions. Start the backend and try again.");
    }
  }, []);

  React.useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  const loadFiles = React.useCallback(async (currentSessionId: string) => {
    try {
      const list = await listChangedFilesV2(currentSessionId);
      setFiles(list.items);
      setFilesError(null);
      setPatchId((current) =>
        current && list.items.some((item) => item.patch_id === current)
          ? current
          : list.items[0]?.patch_id ?? null
      );
    } catch {
      setFiles([]);
      setFilesError("Could not load changed files for this session.");
      setPatchId(null);
    }
  }, []);

  React.useEffect(() => {
    if (!sessionId) {
      setFiles(null);
      setPatchId(null);
      return;
    }
    void loadFiles(sessionId);
  }, [sessionId, loadFiles]);

  const loadPatch = React.useCallback(async (currentSessionId: string, currentPatchId: string) => {
    try {
      const detail = await getPatchDiffV2(currentSessionId, currentPatchId);
      setPatch(detail);
      setPatchError(null);
      setEditValue(detail.updated);
      setMode("diff");
    } catch {
      setPatch(null);
      setPatchError("Could not load this patch's diff.");
    }
  }, []);

  React.useEffect(() => {
    if (!sessionId || !patchId) {
      setPatch(null);
      setEditValue("");
      return;
    }
    void loadPatch(sessionId, patchId);
  }, [sessionId, patchId, loadPatch]);

  async function handleApply() {
    if (!sessionId || !patch) {
      return;
    }
    setActionBusy(true);
    try {
      let current = patch;
      if (editValue !== patch.updated) {
        current = await overridePatchContentV2(sessionId, patch.patch_id, editValue);
        setPatch(current);
      }
      const result = await applyPatchV2(sessionId, current.patch_id, true);
      toast({
        title: result.applied ? "Patch applied" : "Apply did not complete",
        description: result.message,
        variant: result.applied ? "default" : "destructive",
      });
      await loadFiles(sessionId);
      await loadPatch(sessionId, current.patch_id);
    } catch (error) {
      toast({
        title: "Apply failed",
        description: error instanceof Error ? error.message : "Unexpected error.",
        variant: "destructive",
      });
    } finally {
      setActionBusy(false);
    }
  }

  async function handleDiscard() {
    if (!sessionId || !patch) {
      return;
    }
    setActionBusy(true);
    try {
      const discarded = await discardPatchV2(sessionId, patch.patch_id);
      setPatch(discarded);
      toast({ title: "Patch discarded", description: patch.path });
      await loadFiles(sessionId);
    } catch (error) {
      toast({
        title: "Discard failed",
        description: error instanceof Error ? error.message : "Unexpected error.",
        variant: "destructive",
      });
    } finally {
      setActionBusy(false);
    }
  }

  const canAct = !actionBusy && !!patch && patch.status === "proposed";

  return (
    <div className="flex flex-col gap-6 p-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-2">
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-2">Patches</p>
          <h1 className="font-serif text-2xl font-semibold text-ds-fg">Review patches</h1>
          <p className="text-sm text-ds-fg-2">
            Review the diff or switch to Edit, then apply or discard via the patch review API.
          </p>
        </div>
        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-ds-fg-2">Session</span>
          <Select
            value={sessionId ?? undefined}
            onValueChange={(value) => setSessionId(value)}
            disabled={!sessions || sessions.length === 0}
          >
            <SelectTrigger className="w-[280px] border-ds-line bg-ds-bg-2">
              <SelectValue placeholder="Select a session" />
            </SelectTrigger>
            <SelectContent>
              {(sessions ?? []).map((session) => (
                <SelectItem key={session.session_id} value={session.session_id}>
                  {session.goal || session.session_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
      </header>

      {sessionsError && <p className="text-sm text-ds-danger">{sessionsError}</p>}

      {!sessionId ? (
        <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
          <CardContent className="pt-6 text-sm text-ds-fg-2">
            {sessions === null ? "Loading sessions..." : "No sessions yet. Create one to review patches."}
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
          <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
            <CardContent className="pt-6">
              {files === null ? (
                <div className="flex flex-col gap-2">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              ) : (
                <>
                  {filesError && <p className="mb-2 text-sm text-ds-danger">{filesError}</p>}
                  <PatchFileList files={files} selectedPatchId={patchId} onSelect={setPatchId} />
                </>
              )}
            </CardContent>
          </Card>

          <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
            <CardContent className="flex flex-col gap-4 pt-6">
              {patchError && <p className="text-sm text-ds-danger">{patchError}</p>}
              {!patch ? (
                <p className="text-sm text-ds-fg-2">
                  {patchId ? "Loading patch..." : "Select a file to review its diff."}
                </p>
              ) : (
                <>
                  <PatchSegmentedViewer
                    path={patch.path}
                    isDryRun={patch.status === "proposed"}
                    diff={patch.diff}
                    mode={mode}
                    onModeChange={setMode}
                    editValue={editValue}
                    onEditValueChange={setEditValue}
                  />
                  <div className="flex flex-wrap justify-end gap-2 border-t border-ds-line pt-4">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => void handleDiscard()}
                      disabled={!canAct}
                    >
                      Discard
                    </Button>
                    <Button
                      type="button"
                      onClick={() => void handleApply()}
                      disabled={!canAct}
                      className="bg-ds-success text-white hover:bg-ds-success/90"
                    >
                      Apply approved patch
                    </Button>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
