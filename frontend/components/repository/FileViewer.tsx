"use client";

import * as React from "react";

import { getRepositoryFileV2, type FileContentV2 } from "@/lib/api_v2";

/** Props for {@link FileViewer}. */
export type FileViewerProps = {
  /** Project-relative path of the file to display, or `null` for none selected. */
  path: string | null;
};

/**
 * Read-only in-app viewer for one project file (E43-S4-T3), fetched via
 * `GET /v2/repository/file`. Monospace, line-numbered text; binary files
 * are flagged rather than garbled, and oversized files show a clear
 * truncation notice instead of silently clipping content.
 *
 * @param props - See {@link FileViewerProps}.
 * @returns The file's content, or an empty/loading/error state.
 */
export function FileViewer({ path }: FileViewerProps): React.JSX.Element {
  const [file, setFile] = React.useState<FileContentV2 | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!path) {
      setFile(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRepositoryFileV2(path)
      .then((content) => {
        if (!cancelled) {
          setFile(content);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Failed to load this file.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  if (!path) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm text-muted-foreground">
        Select a file to view its contents.
      </div>
    );
  }
  if (loading) {
    return <div className="p-4 text-sm text-muted-foreground">Loading {path}…</div>;
  }
  if (error) {
    return (
      <div className="p-4 text-sm text-destructive" role="alert">
        {error}
      </div>
    );
  }
  if (!file) {
    return <></>;
  }
  if (file.binary) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        <p className="font-mono text-xs">{file.path}</p>
        <p className="mt-2">This file is not text and can&apos;t be previewed here.</p>
      </div>
    );
  }

  const lines = file.content.split("\n");

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <code className="text-xs">{file.path}</code>
        {file.truncated ? (
          <span className="text-xs text-muted-foreground">Showing the first part of a larger file</span>
        ) : null}
      </div>
      <pre className="flex-1 overflow-auto p-0 text-xs leading-relaxed">
        <code>
          {lines.map((line, index) => (
            <div key={index} className="flex">
              <span className="w-10 shrink-0 select-none pr-3 text-right text-muted-foreground">
                {index + 1}
              </span>
              <span className="whitespace-pre-wrap break-all">{line}</span>
            </div>
          ))}
        </code>
      </pre>
    </div>
  );
}

export default FileViewer;
