"use client";

import { ChevronRight, File, Folder, Loader2 } from "lucide-react";
import * as React from "react";

import { getRepositoryTreeV2, type FileTreeEntryV2 } from "@/lib/api_v2";

/** Props for {@link FileTreeBrowser}. */
export type FileTreeBrowserProps = {
  /** Called with a file's project-relative path when the operator clicks it. */
  onSelectFile: (path: string) => void;
  /** The currently open file's path, for highlighting the selected row. */
  selectedPath: string | null;
};

/** Cached listing state for one directory node. */
type DirState = {
  entries: FileTreeEntryV2[] | null;
  expanded: boolean;
  loading: boolean;
  error: string | null;
};

/**
 * Lazily-expanding project file tree (E43-S4-T2), driven by
 * `GET /v2/repository/tree`. Each directory's children are fetched only
 * when it is first expanded, so a large generated project never pays for a
 * full recursive listing up front.
 *
 * @param props - See {@link FileTreeBrowserProps}.
 * @returns The browsable tree, rooted at the project root.
 */
export function FileTreeBrowser({ onSelectFile, selectedPath }: FileTreeBrowserProps): React.JSX.Element {
  const [dirs, setDirs] = React.useState<Record<string, DirState>>({});

  const loadDir = React.useCallback((path: string) => {
    setDirs((current) => ({
      ...current,
      [path]: { entries: current[path]?.entries ?? null, expanded: true, loading: true, error: null },
    }));
    getRepositoryTreeV2(path)
      .then((tree) => {
        setDirs((current) => ({
          ...current,
          [path]: { entries: tree.entries, expanded: true, loading: false, error: null },
        }));
      })
      .catch(() => {
        setDirs((current) => ({
          ...current,
          [path]: { entries: null, expanded: true, loading: false, error: "Failed to load directory." },
        }));
      });
  }, []);

  React.useEffect(() => {
    loadDir("");
  }, [loadDir]);

  function toggleDir(path: string) {
    const state = dirs[path];
    if (!state || state.entries === null) {
      loadDir(path);
      return;
    }
    setDirs((current) => ({ ...current, [path]: { ...state, expanded: !state.expanded } }));
  }

  function renderDir(path: string, depth: number): React.ReactNode {
    const state = dirs[path];
    if (!state) {
      return null;
    }
    if (state.loading && state.entries === null) {
      return (
        <li className="flex items-center gap-2 py-1 text-xs text-muted-foreground" style={{ paddingLeft: depth * 16 }}>
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
          Loading…
        </li>
      );
    }
    if (state.error) {
      return (
        <li className="py-1 text-xs text-destructive" style={{ paddingLeft: depth * 16 }}>
          {state.error}
        </li>
      );
    }
    return (state.entries ?? []).map((entry) => (
      <React.Fragment key={entry.path}>
        <li>
          <button
            type="button"
            onClick={() => (entry.type === "directory" ? toggleDir(entry.path) : onSelectFile(entry.path))}
            className={`flex w-full items-center gap-1.5 rounded-sm px-1 py-1 text-left text-sm hover:bg-muted ${
              selectedPath === entry.path ? "bg-muted font-medium" : ""
            }`}
            style={{ paddingLeft: depth * 16 + 4 }}
          >
            {entry.type === "directory" ? (
              <ChevronRight
                className={`h-3.5 w-3.5 shrink-0 transition-transform ${dirs[entry.path]?.expanded ? "rotate-90" : ""}`}
                aria-hidden="true"
              />
            ) : (
              <span className="w-3.5 shrink-0" aria-hidden="true" />
            )}
            {entry.type === "directory" ? (
              <Folder className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
            ) : (
              <File className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
            )}
            <span className="truncate">{entry.name}</span>
          </button>
        </li>
        {entry.type === "directory" && dirs[entry.path]?.expanded ? (
          <ul>{renderDir(entry.path, depth + 1)}</ul>
        ) : null}
      </React.Fragment>
    ));
  }

  const root = dirs[""];
  if (!root || (root.loading && root.entries === null)) {
    return (
      <div className="flex items-center gap-2 p-3 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Loading project files…
      </div>
    );
  }
  if (root.error) {
    return <p className="p-3 text-sm text-destructive">{root.error}</p>;
  }
  if ((root.entries ?? []).length === 0) {
    return <p className="p-3 text-sm text-muted-foreground">The project has no files yet.</p>;
  }

  return (
    <ul aria-label="Project files" className="flex flex-col overflow-y-auto p-1">
      {renderDir("", 0)}
    </ul>
  );
}

export default FileTreeBrowser;
