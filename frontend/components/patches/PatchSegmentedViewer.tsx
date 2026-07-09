// Right-hand Diff/Edit segmented viewer of the Patches review screen
// (E17-S3-T2): a Radix Tabs segmented control toggling between the
// read-only unified diff and a monospace editor, plus a dry-run badge.
// The edit segment's value is a controlled prop so it survives segment
// switches even though the inactive `TabsContent` unmounts.

import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

import { PatchDiffView } from "./PatchDiffView";

export type PatchViewerMode = "diff" | "edit";

export type PatchSegmentedViewerProps = {
  /** Path of the file currently shown, for the viewer header. */
  path: string;
  /** Whether the patch has not been applied yet (drives the dry-run badge). */
  isDryRun: boolean;
  /** Unified diff text rendered by the Diff segment. */
  diff: string;
  /** Active segment. */
  mode: PatchViewerMode;
  /** Called when the operator switches segments. */
  onModeChange: (mode: PatchViewerMode) => void;
  /** Editable file content backing the Edit segment (lifted to the caller). */
  editValue: string;
  /** Called with the new content as the operator types in the Edit segment. */
  onEditValueChange: (value: string) => void;
};

const segmentTriggerClass =
  "rounded-ds-sm px-3 py-1 text-xs font-semibold text-ds-fg-2 transition-colors " +
  "data-[state=active]:bg-ds-bg-4 data-[state=active]:text-ds-fg data-[state=active]:shadow-ds-sm";

/**
 * Render the segmented Diff/Edit viewer: a header with the file path and a
 * dry-run indicator, a Diff/Edit tab list, and the corresponding segment
 * content.
 *
 * @param props - {@link PatchSegmentedViewerProps}.
 * @returns The segmented viewer.
 */
export function PatchSegmentedViewer({
  path,
  isDryRun,
  diff,
  mode,
  onModeChange,
  editValue,
  onEditValueChange,
}: PatchSegmentedViewerProps) {
  return (
    <Tabs
      value={mode}
      onValueChange={(value) => onModeChange(value === "edit" ? "edit" : "diff")}
      className="flex h-full flex-col gap-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-mono text-sm text-ds-fg" title={path}>
            {path}
          </span>
          {isDryRun && (
            <Badge
              variant="outline"
              className="flex-none border-ds-warn/40 bg-ds-warn/10 text-ds-warn"
            >
              Dry-run · nothing written yet
            </Badge>
          )}
        </div>
        <TabsList className="h-8 gap-1 bg-ds-bg-3 p-1">
          <TabsTrigger value="diff" className={cn(segmentTriggerClass)}>
            Diff
          </TabsTrigger>
          <TabsTrigger value="edit" className={cn(segmentTriggerClass)}>
            Edit
          </TabsTrigger>
        </TabsList>
      </div>

      <TabsContent value="diff" className="mt-0 flex-1 overflow-y-auto">
        <PatchDiffView diff={diff} />
      </TabsContent>
      <TabsContent value="edit" className="mt-0 flex-1">
        <label className="flex h-full flex-col gap-1.5">
          <span className="sr-only">Edit the resulting content of {path}</span>
          <textarea
            value={editValue}
            onChange={(event) => onEditValueChange(event.target.value)}
            spellCheck={false}
            className={cn(
              "h-full min-h-[280px] w-full flex-1 resize-y rounded-ds-md border border-ds-line",
              "bg-ds-bg-2 px-3 py-2 font-mono text-[12.5px] leading-[1.7] text-ds-fg shadow-sm",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ds-accent"
            )}
          />
        </label>
      </TabsContent>
    </Tabs>
  );
}
