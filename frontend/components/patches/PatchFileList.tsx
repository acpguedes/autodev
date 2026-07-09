// Left-hand file panel of the Patches review screen (E17-S3-T1): a
// keyboard-navigable list of changed files with per-file +/- line counts,
// used to pick which patch is shown in the Diff/Edit viewer.

import type { ChangedFileV2 } from "@/lib/api_patches_v2";
import { cn } from "@/lib/utils";

/** Split a repo-relative path into its directory label and file name. */
function splitPath(path: string): { dir: string; base: string } {
  const parts = path.split("/");
  const base = parts.pop() ?? path;
  return { dir: parts.length ? `${parts.join("/")}/` : "root", base };
}

function statusLabel(status: ChangedFileV2["status"]): string {
  switch (status) {
    case "applied":
      return "Applied";
    case "discarded":
      return "Discarded";
    default:
      return "Proposed";
  }
}

function statusDotClass(status: ChangedFileV2["status"]): string {
  switch (status) {
    case "applied":
      return "bg-ds-success";
    case "discarded":
      return "bg-ds-danger";
    default:
      return "bg-ds-accent";
  }
}

export type PatchFileListProps = {
  /** Changed files to list, in the order returned by the changed-files endpoint. */
  files: ChangedFileV2[];
  /** `patch_id` of the currently selected file, if any. */
  selectedPatchId: string | null;
  /** Called with a file's `patch_id` when the operator selects it. */
  onSelect: (patchId: string) => void;
};

/**
 * Render the changed-file list panel: a summary line ("N files · +A -R")
 * followed by one focusable row per file, each showing its directory,
 * name, status, and add/remove line counts.
 *
 * @param props - {@link PatchFileListProps}.
 * @returns The file list panel.
 */
export function PatchFileList({ files, selectedPatchId, onSelect }: PatchFileListProps) {
  const totals = files.reduce(
    (acc, file) => ({
      added: acc.added + file.added_lines,
      removed: acc.removed + file.removed_lines,
    }),
    { added: 0, removed: 0 }
  );

  return (
    <nav aria-label="Changed files" className="flex h-full flex-col gap-3">
      <p className="text-xs font-medium text-ds-fg-2">
        {files.length === 0
          ? "No changed files"
          : `${files.length} file${files.length === 1 ? "" : "s"} · `}
        {files.length > 0 && (
          <>
            <span className="text-ds-add-fg">+{totals.added}</span>{" "}
            <span className="text-ds-del-fg">-{totals.removed}</span>
          </>
        )}
      </p>

      {files.length === 0 ? (
        <p className="rounded-ds-md border border-dashed border-ds-line px-3 py-4 text-sm text-ds-fg-2">
          Propose a patch to see it listed here for review.
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {files.map((file) => {
            const { dir, base } = splitPath(file.path);
            const selected = file.patch_id === selectedPatchId;
            return (
              <li key={file.patch_id}>
                <button
                  type="button"
                  aria-current={selected ? "true" : undefined}
                  onClick={() => onSelect(file.patch_id)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-ds-md border px-3 py-2 text-left transition-colors",
                    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ds-accent",
                    selected
                      ? "border-ds-accent/40 bg-ds-accent/10"
                      : "border-transparent hover:bg-ds-bg-3"
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={cn("h-1.5 w-1.5 flex-none rounded-full", statusDotClass(file.status))}
                  />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-sm font-medium text-ds-fg">{base}</span>
                    <span className="truncate text-[11px] text-ds-fg-2">
                      {dir} · {statusLabel(file.status)}
                    </span>
                  </span>
                  <span className="flex flex-none items-baseline gap-1.5 font-mono text-[11px]">
                    <span className="text-ds-add-fg">+{file.added_lines}</span>
                    <span className="text-ds-del-fg">-{file.removed_lines}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
