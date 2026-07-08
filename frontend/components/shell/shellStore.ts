// Framework-agnostic state store for the Execution Control Center shell
// (E15-S2). Holds the panel open/width and active-nav state and mirrors it to
// a storage backend (`sessionStorage` in the browser) under a single key, so
// the panel stays open across client navigation within a session. The store
// is intentionally free of React so it can be unit-tested in the node
// environment the way the panel registry is, and so `ShellProvider` can bind
// it through `useSyncExternalStore` for hydration-safe reads.

/** Minimal storage surface the store depends on (a `sessionStorage` subset). */
export interface ShellStorage {
  /** Return the value previously stored under `key`, or `null`. */
  getItem(key: string): string | null;
  /** Persist `value` under `key`. */
  setItem(key: string, value: string): void;
}

/** The persisted shell state. */
export interface ShellState {
  /** Whether the right execution panel is open. */
  readonly panelOpen: boolean;
  /** Current execution-panel width in CSS pixels. */
  readonly panelWidth: number;
  /** Key of the active primary/legacy nav item (see `navModel`). */
  readonly activeNav: string;
}

/** `sessionStorage` key that holds the serialized {@link ShellState}. */
export const SHELL_STORAGE_KEY = "autodev.shell.v1";

/** Default execution-panel width, per ADR-012 §4 (prototype's 400px panel). */
export const DEFAULT_PANEL_WIDTH = 400;

/** Inclusive bounds the panel width is clamped to before it is stored. */
export const MIN_PANEL_WIDTH = 320;
export const MAX_PANEL_WIDTH = 720;

/** Immutable default state used on the server and before hydration. */
export const DEFAULT_SHELL_STATE: ShellState = Object.freeze({
  panelOpen: false,
  panelWidth: DEFAULT_PANEL_WIDTH,
  activeNav: "chat",
});

/**
 * Clamp a candidate panel width into the supported range.
 *
 * @param width - Requested width in CSS pixels.
 * @returns The width bounded to `[MIN_PANEL_WIDTH, MAX_PANEL_WIDTH]`, or the
 *   default when the input is not a finite number.
 */
export function clampPanelWidth(width: number): number {
  if (!Number.isFinite(width)) {
    return DEFAULT_PANEL_WIDTH;
  }
  return Math.min(MAX_PANEL_WIDTH, Math.max(MIN_PANEL_WIDTH, Math.round(width)));
}

/**
 * Coerce untrusted parsed JSON into a valid {@link ShellState}, discarding
 * malformed fields so a corrupt storage entry never propagates bad state.
 *
 * @param raw - Value parsed from storage (of unknown shape).
 * @returns A well-formed shell state.
 */
export function sanitizeShellState(raw: unknown): ShellState {
  if (typeof raw !== "object" || raw === null) {
    return DEFAULT_SHELL_STATE;
  }
  const candidate = raw as Record<string, unknown>;
  return {
    panelOpen:
      typeof candidate.panelOpen === "boolean"
        ? candidate.panelOpen
        : DEFAULT_SHELL_STATE.panelOpen,
    panelWidth:
      typeof candidate.panelWidth === "number"
        ? clampPanelWidth(candidate.panelWidth)
        : DEFAULT_SHELL_STATE.panelWidth,
    activeNav:
      typeof candidate.activeNav === "string" && candidate.activeNav.length > 0
        ? candidate.activeNav
        : DEFAULT_SHELL_STATE.activeNav,
  };
}

/** The store interface consumed by `ShellProvider` and by unit tests. */
export interface ShellStore {
  /** Current state (referentially stable until a mutation occurs). */
  getSnapshot(): ShellState;
  /** Server/pre-hydration snapshot — always the defaults. */
  getServerSnapshot(): ShellState;
  /** Subscribe to state changes; returns an unsubscribe function. */
  subscribe(listener: () => void): () => void;
  /** Open or close the execution panel. */
  setPanelOpen(open: boolean): void;
  /** Toggle the execution panel. */
  togglePanel(): void;
  /** Set the execution-panel width (clamped to the supported range). */
  setPanelWidth(width: number): void;
  /** Record the active nav item key. */
  setActiveNav(nav: string): void;
}

/**
 * Create a shell store bound to an optional storage backend.
 *
 * @param storage - Backend to hydrate from and persist to; pass `null` for an
 *   in-memory store (server rendering or tests without persistence).
 * @returns A {@link ShellStore}.
 */
export function createShellStore(storage: ShellStorage | null): ShellStore {
  const load = (): ShellState => {
    if (!storage) {
      return DEFAULT_SHELL_STATE;
    }
    try {
      const raw = storage.getItem(SHELL_STORAGE_KEY);
      return raw ? sanitizeShellState(JSON.parse(raw)) : DEFAULT_SHELL_STATE;
    } catch {
      return DEFAULT_SHELL_STATE;
    }
  };

  let state: ShellState = load();
  const listeners = new Set<() => void>();

  const persist = (): void => {
    if (!storage) {
      return;
    }
    try {
      storage.setItem(SHELL_STORAGE_KEY, JSON.stringify(state));
    } catch {
      // Storage may be full or unavailable; keep the in-memory state.
    }
  };

  const commit = (next: ShellState): void => {
    if (
      next.panelOpen === state.panelOpen &&
      next.panelWidth === state.panelWidth &&
      next.activeNav === state.activeNav
    ) {
      return;
    }
    state = next;
    persist();
    listeners.forEach((listener) => listener());
  };

  return {
    getSnapshot: () => state,
    getServerSnapshot: () => DEFAULT_SHELL_STATE,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setPanelOpen: (open) => commit({ ...state, panelOpen: open }),
    togglePanel: () => commit({ ...state, panelOpen: !state.panelOpen }),
    setPanelWidth: (width) => commit({ ...state, panelWidth: clampPanelWidth(width) }),
    setActiveNav: (nav) => commit({ ...state, activeNav: nav }),
  };
}

/**
 * Resolve the browser `sessionStorage` when it is usable.
 *
 * @returns `sessionStorage` when available and writable, else `null` (SSR or
 *   privacy modes that throw on access).
 */
function resolveBrowserStorage(): ShellStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const storage = window.sessionStorage;
    const probe = "__autodev_shell_probe__";
    storage.setItem(probe, "1");
    storage.removeItem(probe);
    return storage;
  } catch {
    return null;
  }
}

/** Process-wide singleton bound to the real `sessionStorage` on the client. */
export const shellStore: ShellStore = createShellStore(resolveBrowserStorage());
