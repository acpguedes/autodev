// Pure parsing helpers for the unified-diff strings returned by the E16-S3
// patch review API (`PatchDetailV2.diff`). The backend generates these via
// Python's `difflib.unified_diff` (backend/patches/engine.py::generate_patch):
// `---`/`+++` file-header lines, `@@ -a,b +c,d @@` hunk headers, then
// `+`/`-`/` `-prefixed content lines. Kept dependency-free so it can run in
// both the browser and Storybook/Vitest without a diff library.

/** Kind of a single row rendered in the Diff segment of the viewer. */
export type DiffLineKind = "add" | "del" | "context" | "hunk" | "header";

/** One renderable row of a parsed unified diff. */
export type DiffLine = {
  kind: DiffLineKind;
  /** Line content with the leading `+`/`-`/` ` marker stripped (kept for hunk/header rows). */
  text: string;
  /** 1-based line number in the new (updated) file; unset for `del`/`hunk`/`header` rows. */
  newLineNo: number | null;
};

const HUNK_HEADER_PATTERN = /^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@/;

/**
 * Parse a unified-diff string into renderable rows with computed gutter
 * line numbers, so the Diff segment can render add/del/context lines with
 * a running "new file" line count (mirroring the prototype's gutter, which
 * only numbers non-deleted lines).
 *
 * @param diff - Unified diff text (possibly empty when there are no changes).
 * @returns One {@link DiffLine} per row of the diff, in order.
 */
export function parseUnifiedDiff(diff: string): DiffLine[] {
  if (!diff) {
    return [];
  }
  const lines: DiffLine[] = [];
  let newLineNo = 0;

  for (const raw of diff.replace(/\n$/, "").split("\n")) {
    if (raw.startsWith("--- ") || raw.startsWith("+++ ")) {
      lines.push({ kind: "header", text: raw, newLineNo: null });
      continue;
    }
    const hunkMatch = HUNK_HEADER_PATTERN.exec(raw);
    if (hunkMatch) {
      newLineNo = Number(hunkMatch[2]) - 1;
      lines.push({ kind: "hunk", text: raw, newLineNo: null });
      continue;
    }
    if (raw.startsWith("+")) {
      newLineNo += 1;
      lines.push({ kind: "add", text: raw.slice(1), newLineNo });
      continue;
    }
    if (raw.startsWith("-")) {
      lines.push({ kind: "del", text: raw.slice(1), newLineNo: null });
      continue;
    }
    if (raw.startsWith(" ")) {
      newLineNo += 1;
      lines.push({ kind: "context", text: raw.slice(1), newLineNo });
      continue;
    }
    if (raw.startsWith("\\")) {
      // "\ No newline at end of file" — not attributable to either side.
      continue;
    }
    // Defensive fallback for any unrecognized row shape.
    newLineNo += 1;
    lines.push({ kind: "context", text: raw, newLineNo });
  }

  return lines;
}

/**
 * Fold the "new file" side of a unified diff back into plain content, by
 * dropping deleted lines and stripping the `+`/` ` markers from the rest.
 * Used to seed the Edit segment's textarea from a freshly loaded diff.
 *
 * @param diff - Unified diff text.
 * @returns The reconstructed updated-file content.
 */
export function foldDiffToUpdatedContent(diff: string): string {
  return parseUnifiedDiff(diff)
    .filter((line) => line.kind === "add" || line.kind === "context")
    .map((line) => line.text)
    .join("\n");
}
