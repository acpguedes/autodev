"use client";

import { useTheme } from "next-themes";
import dynamic from "next/dynamic";
import * as React from "react";
import useSWR from "swr";

import { useShell } from "@/components/shell/ShellProvider";
import { useTranslations } from "@/lib/i18n";
import { listProjectsV2 } from "@/lib/projects_v2";
import {
  CLOSE_FORBIDDEN,
  CLOSE_UNAUTHENTICATED,
  generateTerminalId,
  isProjectMismatch,
  openTerminalSocket,
  terminalSocketUrl,
  type TerminalSocketHandle,
} from "@/lib/terminal_socket";

import type { TerminalViewApi } from "./TerminalView";

// xterm touches `window` at import, so it is loaded client-side only and stays
// out of the main bundle.
const TerminalView = dynamic(() => import("./TerminalView"), {
  ssr: false,
  loading: () => null,
});

type Phase =
  | "connecting"
  | "open"
  | "mismatch"
  | "exited"
  | "closed"
  | "unauthenticated"
  | "forbidden";

/**
 * Interactive terminal for the active project (E65-S3/S4). Owns the per-project
 * terminal id, the socket lifecycle, and the user-visible handling of a stale
 * id (the server reporting a different project root discards the id and offers
 * a new session instead of continuing in an ambiguous shell).
 *
 * @param props - `active` is whether the Terminal tab is currently visible.
 * @returns The terminal surface with a status line.
 */
export function TerminalPanel({ active }: { active: boolean }): React.JSX.Element {
  const { t } = useTranslations();
  const { resolvedTheme } = useTheme();
  const { terminalIds, setTerminalId } = useShell();
  const projects = useSWR("shell:projects", listProjectsV2, { shouldRetryOnError: false });

  const projectRoot =
    projects.data?.items.find((p) => p.projectId === projects.data?.activeProjectId)?.rootPath ??
    null;
  const terminalId = projectRoot ? terminalIds[projectRoot] : undefined;

  const [view, setView] = React.useState<TerminalViewApi | null>(null);
  const [phase, setPhase] = React.useState<Phase>("connecting");
  const [attempt, setAttempt] = React.useState(0);
  const socketRef = React.useRef<TerminalSocketHandle | null>(null);

  // A project switch starts from a clean slate (the stale id is per root).
  React.useEffect(() => {
    setPhase("connecting");
  }, [projectRoot]);

  // Generate an id for a project that has none, unless the user must first
  // acknowledge a discarded/ended session.
  React.useEffect(() => {
    if (projectRoot && !terminalId && phase !== "mismatch" && phase !== "exited") {
      setTerminalId(projectRoot, generateTerminalId());
    }
  }, [projectRoot, terminalId, phase, setTerminalId]);

  React.useEffect(() => {
    if (!view || !projectRoot || !terminalId) {
      return;
    }
    const root = projectRoot;
    view.reset();
    setPhase("connecting");
    const socket = openTerminalSocket(terminalSocketUrl(terminalId), {
      onOpen: () => {
        setPhase("open");
        const { cols, rows } = view.size();
        socket.sendResize(cols, rows);
      },
      onFrame: (frame) => {
        if (frame.type === "output") {
          view.write(frame.data);
        } else if (frame.type === "info") {
          if (isProjectMismatch(frame.projectRoot, root)) {
            socket.close();
            setTerminalId(root, null);
            setPhase("mismatch");
          }
        } else {
          setTerminalId(root, null);
          setPhase("exited");
        }
      },
      onClose: (code) => {
        setPhase((current) => {
          if (current === "mismatch" || current === "exited") {
            return current;
          }
          if (code === CLOSE_UNAUTHENTICATED) {
            return "unauthenticated";
          }
          return code === CLOSE_FORBIDDEN ? "forbidden" : "closed";
        });
      },
    });
    socketRef.current = socket;
    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [view, projectRoot, terminalId, attempt, setTerminalId]);

  const startNewSession = (): void => {
    if (projectRoot) {
      setPhase("connecting");
      setTerminalId(projectRoot, generateTerminalId());
    }
  };

  let message: string | null = null;
  let actionLabel: string | null = null;
  if (!projectRoot && projects.data) {
    message = t("terminal.noProject");
  } else if (phase === "mismatch") {
    message = t("terminal.mismatchNotice");
    actionLabel = t("terminal.newSession");
  } else if (phase === "exited") {
    message = t("terminal.exited");
    actionLabel = t("terminal.newSession");
  } else if (phase === "unauthenticated") {
    message = t("terminal.unauthenticated");
  } else if (phase === "forbidden") {
    message = t("terminal.forbidden");
  } else if (phase === "closed") {
    message = t("terminal.disconnected");
    actionLabel = t("terminal.reconnect");
  } else if (phase === "connecting") {
    message = t("terminal.connecting");
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-ds-bg-2">
      {message ? (
        <div
          role="status"
          className="flex shrink-0 items-center justify-between gap-2 border-b border-ds-line px-3 py-2 text-[12px] text-ds-fg-2"
        >
          <span>{message}</span>
          {actionLabel ? (
            <button
              type="button"
              onClick={phase === "closed" ? () => setAttempt((n) => n + 1) : startNewSession}
              className="shrink-0 rounded-ds-sm border border-ds-line px-2 py-1 text-ds-fg hover:bg-ds-bg-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent"
            >
              {actionLabel}
            </button>
          ) : null}
        </div>
      ) : null}
      <div className="min-h-0 flex-1">
        <TerminalView
          active={active}
          themeKey={resolvedTheme}
          label={t("terminal.region")}
          onReady={setView}
          onData={(data) => socketRef.current?.sendInput(data)}
          onResize={(cols, rows) => socketRef.current?.sendResize(cols, rows)}
        />
      </div>
    </div>
  );
}

export default TerminalPanel;
