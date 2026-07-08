"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { shellStore } from "./shellStore";

/** Contextual header content a page publishes for the 64px header. */
export interface ShellHeaderContent {
  /** Primary view title. */
  title: string;
  /** Optional secondary line under the title. */
  subtitle?: string;
}

/** Options a page passes to {@link useShellHeader}. */
export interface ShellHeaderOptions extends ShellHeaderContent {
  /**
   * Handler invoked by the header's "+ New session" action while this page is
   * mounted. When omitted, the action navigates to the Chat route.
   */
  onNewSession?: (() => void) | null;
}

/** Everything exposed through the shell context. */
export interface ShellContextValue {
  /** Whether the execution panel is open. */
  panelOpen: boolean;
  /** Current execution-panel width in CSS pixels. */
  panelWidth: number;
  /** Active nav item key. */
  activeNav: string;
  /** Open or close the execution panel. */
  setPanelOpen: (open: boolean) => void;
  /** Toggle the execution panel. */
  togglePanel: () => void;
  /** Record the active nav item key. */
  setActiveNav: (nav: string) => void;
  /** Current contextual-header content. */
  header: ShellHeaderContent;
  /** Replace the contextual-header content. */
  setHeader: (content: ShellHeaderContent) => void;
  /** Register (or clear) the page-scoped "+ New session" handler. */
  setNewSessionHandler: (handler: (() => void) | null) => void;
  /** Run the active "+ New session" handler, or navigate to Chat. */
  triggerNewSession: () => void;
  /** Content rendered inside the execution panel, if any. */
  panelContent: React.ReactNode;
  /** Replace the execution-panel content. */
  setPanelContent: (content: React.ReactNode) => void;
}

const ShellContext = React.createContext<ShellContextValue | null>(null);

const DEFAULT_HEADER: ShellHeaderContent = { title: "AutoDev Architect" };

/**
 * Provide shell state (panel, nav, header, execution-panel content) to the app
 * shell and every route. Persisted panel/nav state is read through
 * `useSyncExternalStore` so server and client agree on the first paint and the
 * store hydrates from `sessionStorage` only on the client.
 *
 * @param props - Standard children.
 * @returns The context provider.
 */
export function ShellProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const router = useRouter();
  const state = React.useSyncExternalStore(
    shellStore.subscribe,
    shellStore.getSnapshot,
    shellStore.getServerSnapshot
  );

  const [header, setHeader] = React.useState<ShellHeaderContent>(DEFAULT_HEADER);
  const [panelContent, setPanelContent] = React.useState<React.ReactNode>(null);
  // A function is stored in a ref rather than state to avoid React's
  // updater-function overload and needless re-renders; the header reads it at
  // click time, so reactivity is unnecessary.
  const newSessionHandlerRef = React.useRef<(() => void) | null>(null);

  const setNewSessionHandler = React.useCallback((handler: (() => void) | null) => {
    newSessionHandlerRef.current = handler;
  }, []);

  const triggerNewSession = React.useCallback(() => {
    if (newSessionHandlerRef.current) {
      newSessionHandlerRef.current();
    } else {
      router.push("/");
    }
  }, [router]);

  const value = React.useMemo<ShellContextValue>(
    () => ({
      panelOpen: state.panelOpen,
      panelWidth: state.panelWidth,
      activeNav: state.activeNav,
      setPanelOpen: shellStore.setPanelOpen,
      togglePanel: shellStore.togglePanel,
      setActiveNav: shellStore.setActiveNav,
      header,
      setHeader,
      setNewSessionHandler,
      triggerNewSession,
      panelContent,
      setPanelContent,
    }),
    [state, header, panelContent, setNewSessionHandler, triggerNewSession]
  );

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

/**
 * Access the shell context.
 *
 * @returns The shell context value.
 * @throws Error when called outside a {@link ShellProvider}.
 */
export function useShell(): ShellContextValue {
  const context = React.useContext(ShellContext);
  if (!context) {
    throw new Error("useShell must be used within a ShellProvider");
  }
  return context;
}

/**
 * Publish contextual-header content (and an optional "+ New session" handler)
 * for the current page. Clears the handler on unmount so it never leaks to the
 * next route.
 *
 * @param options - Header title/subtitle and optional new-session handler.
 */
export function useShellHeader(options: ShellHeaderOptions): void {
  const { setHeader, setNewSessionHandler } = useShell();
  const { title, subtitle, onNewSession } = options;

  React.useEffect(() => {
    setHeader({ title, subtitle });
    setNewSessionHandler(onNewSession ?? null);
    return () => setNewSessionHandler(null);
  }, [title, subtitle, onNewSession, setHeader, setNewSessionHandler]);
}

/**
 * Publish content into the execution panel for the current page and clear it on
 * unmount. Memoize `content` in the caller so the effect does not re-run every
 * render.
 *
 * @param content - Node rendered inside the execution panel.
 */
export function useExecutionPanel(content: React.ReactNode): void {
  const { setPanelContent } = useShell();

  React.useEffect(() => {
    setPanelContent(content);
    return () => setPanelContent(null);
  }, [content, setPanelContent]);
}

/**
 * Null-rendering helper that publishes header content from a server component
 * (which cannot call hooks). Client pages should call {@link useShellHeader}
 * directly instead.
 *
 * @param props - Header content.
 * @returns `null`.
 */
export function ShellHeaderPortal(props: ShellHeaderContent): null {
  useShellHeader(props);
  return null;
}
