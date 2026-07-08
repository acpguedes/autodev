// Unit tests for the shell state store (E15-S2). These run in the node
// project and, like the panel-registry contract tests, exercise persistence
// through an in-memory storage stub — verifying the CNF that "panel state
// persists across navigation within a session" at the store level. Real DOM
// rendering, landmarks, and cross-route persistence are asserted by the
// Playwright e2e in the story's verification step.

import { describe, expect, it, vi } from "vitest";

import {
  DEFAULT_PANEL_WIDTH,
  DEFAULT_SHELL_STATE,
  MAX_PANEL_WIDTH,
  MIN_PANEL_WIDTH,
  SHELL_STORAGE_KEY,
  clampPanelWidth,
  createShellStore,
  sanitizeShellState,
  type ShellStorage,
} from "../shellStore";

/** In-memory {@link ShellStorage} stub mirroring the sessionStorage subset. */
function memoryStorage(): ShellStorage & { raw: Map<string, string> } {
  const raw = new Map<string, string>();
  return {
    raw,
    getItem: (key) => raw.get(key) ?? null,
    setItem: (key, value) => {
      raw.set(key, value);
    },
  };
}

describe("clampPanelWidth", () => {
  it("bounds the width to the supported range and rounds", () => {
    expect(clampPanelWidth(10)).toBe(MIN_PANEL_WIDTH);
    expect(clampPanelWidth(9999)).toBe(MAX_PANEL_WIDTH);
    expect(clampPanelWidth(401.6)).toBe(402);
  });

  it("falls back to the default for non-finite input", () => {
    expect(clampPanelWidth(Number.NaN)).toBe(DEFAULT_PANEL_WIDTH);
    expect(clampPanelWidth(Number.POSITIVE_INFINITY)).toBe(DEFAULT_PANEL_WIDTH);
  });
});

describe("sanitizeShellState", () => {
  it("returns defaults for malformed input", () => {
    expect(sanitizeShellState(null)).toEqual(DEFAULT_SHELL_STATE);
    expect(sanitizeShellState("nope")).toEqual(DEFAULT_SHELL_STATE);
    expect(sanitizeShellState({})).toEqual(DEFAULT_SHELL_STATE);
  });

  it("keeps valid fields and clamps the width", () => {
    expect(
      sanitizeShellState({ panelOpen: true, panelWidth: 5000, activeNav: "plans" })
    ).toEqual({ panelOpen: true, panelWidth: MAX_PANEL_WIDTH, activeNav: "plans" });
  });
});

describe("createShellStore", () => {
  it("starts from defaults with no storage", () => {
    const store = createShellStore(null);
    expect(store.getSnapshot()).toEqual(DEFAULT_SHELL_STATE);
    expect(store.getServerSnapshot()).toEqual(DEFAULT_SHELL_STATE);
  });

  it("mutates state, notifies subscribers, and keeps snapshot referentially stable", () => {
    const store = createShellStore(null);
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);

    const before = store.getSnapshot();
    store.setActiveNav("chat"); // no-op: already the default
    expect(listener).not.toHaveBeenCalled();
    expect(store.getSnapshot()).toBe(before);

    store.setPanelOpen(true);
    store.togglePanel();
    store.setPanelWidth(480);
    store.setActiveNav("sessions");
    expect(listener).toHaveBeenCalledTimes(4);

    const snapshot = store.getSnapshot();
    expect(snapshot).toEqual({ panelOpen: false, panelWidth: 480, activeNav: "sessions" });
    expect(store.getSnapshot()).toBe(snapshot);

    unsubscribe();
    store.setPanelOpen(true);
    expect(listener).toHaveBeenCalledTimes(4);
  });

  it("persists to storage and rehydrates across store instances (survives navigation)", () => {
    const storage = memoryStorage();

    const first = createShellStore(storage);
    first.setPanelOpen(true);
    first.setPanelWidth(520);
    first.setActiveNav("patches");
    expect(storage.raw.has(SHELL_STORAGE_KEY)).toBe(true);

    // A later store instance (as a fresh page/navigation would create) reads
    // the persisted state back.
    const second = createShellStore(storage);
    expect(second.getSnapshot()).toEqual({
      panelOpen: true,
      panelWidth: 520,
      activeNav: "patches",
    });
  });

  it("recovers from corrupt storage without throwing", () => {
    const storage = memoryStorage();
    storage.raw.set(SHELL_STORAGE_KEY, "{not json");
    const store = createShellStore(storage);
    expect(store.getSnapshot()).toEqual(DEFAULT_SHELL_STATE);
  });
});
