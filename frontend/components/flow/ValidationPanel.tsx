"use client";

import { Badge } from "@/components/ui/badge";
import type { ValidationIssue } from "@/lib/flow/validate";
import { cn } from "@/lib/utils";

type ValidationPanelProps = {
  parseErrors: string[];
  issues: ValidationIssue[];
  onSelectNode?: (nodeId: string) => void;
};

/**
 * Real-time validation feedback (E10-S3-T3). Lists YAML parse errors and
 * graph validation issues; issues anchored to a node jump to it on click.
 */
export function ValidationPanel({ parseErrors, issues, onSelectNode }: ValidationPanelProps) {
  if (parseErrors.length === 0 && issues.length === 0) {
    return (
      <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
        No validation issues — the flow is a valid graph.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2" aria-label="Validation issues">
      {parseErrors.map((error, index) => (
        <li
          key={`parse-${index}`}
          className="flex items-start gap-2 rounded-md border border-destructive/50 px-3 py-2 text-sm"
        >
          <Badge variant="destructive">yaml</Badge>
          <span className="text-foreground">{error}</span>
        </li>
      ))}
      {issues.map((issue, index) => {
        const clickable = issue.nodeId !== undefined && onSelectNode !== undefined;
        const body = (
          <>
            <Badge variant="destructive">{issue.code}</Badge>
            <span className="text-foreground">{issue.message}</span>
          </>
        );
        return (
          <li key={`issue-${index}`}>
            {clickable ? (
              <button
                type="button"
                onClick={() => onSelectNode?.(issue.nodeId as string)}
                className={cn(
                  "flex w-full items-start gap-2 rounded-md border border-destructive/50 px-3 py-2 text-left text-sm",
                  "hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                )}
              >
                {body}
              </button>
            ) : (
              <div className="flex items-start gap-2 rounded-md border border-destructive/50 px-3 py-2 text-sm">
                {body}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
