// Read-only unified-diff renderer for the Diff segment of the Patches
// review screen's viewer (E17-S3-T2): line-numbered gutter plus add/del
// row highlighting, driven by `parseUnifiedDiff`.

import { parseUnifiedDiff } from "@/lib/diff";
import { cn } from "@/lib/utils";

export type PatchDiffViewProps = {
  /** Unified diff text, as returned by `PatchDetailV2.diff`. */
  diff: string;
};

/**
 * Render a unified diff as a scrollable, gutter-numbered table: `+`/`-`
 * rows tinted with the add/del design tokens, hunk headers de-emphasized,
 * and a running new-file line number in the gutter for add/context rows.
 *
 * @param props - {@link PatchDiffViewProps}.
 * @returns The read-only diff view.
 */
export function PatchDiffView({ diff }: PatchDiffViewProps) {
  const lines = parseUnifiedDiff(diff);

  if (lines.length === 0) {
    return (
      <p className="rounded-ds-md border border-dashed border-ds-line px-3 py-4 text-sm text-ds-fg-2">
        No changes to display.
      </p>
    );
  }

  return (
    <div
      role="table"
      aria-label="Unified diff"
      className="overflow-x-auto rounded-ds-md border border-ds-line bg-ds-bg-2"
    >
      <div role="rowgroup" className="min-w-full font-mono text-[12.5px] leading-[1.7]">
        {lines.map((line, index) => {
          if (line.kind === "header" || line.kind === "hunk") {
            return (
              <div
                key={index}
                role="row"
                className={cn(
                  "px-3 py-0.5 text-ds-fg-2",
                  line.kind === "hunk" && "border-y border-ds-line bg-ds-bg-3"
                )}
              >
                <span role="cell">{line.text}</span>
              </div>
            );
          }

          const sign = line.kind === "add" ? "+" : line.kind === "del" ? "-" : " ";
          return (
            <div
              key={index}
              role="row"
              className={cn(
                "flex px-3",
                line.kind === "add" && "bg-ds-add-bg text-ds-add-fg",
                line.kind === "del" && "bg-ds-del-bg text-ds-del-fg",
                line.kind === "context" && "text-ds-fg"
              )}
            >
              <span
                role="cell"
                aria-hidden="true"
                className="w-10 flex-none select-none pr-2 text-right text-ds-fg-2"
              >
                {line.newLineNo ?? ""}
              </span>
              <span role="cell" aria-hidden="true" className="w-3 flex-none select-none font-semibold">
                {sign}
              </span>
              <span role="cell" className="min-w-0 flex-1 whitespace-pre-wrap break-all">
                {line.text}
                <span className="sr-only">
                  {" "}
                  ({line.kind === "add" ? "added" : line.kind === "del" ? "removed" : "unchanged"})
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
