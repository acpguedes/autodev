// Navigation model for the Execution Control Center sidebar rail (E15-S2).
// Kept separate from the rail component so the item set and the active-item
// resolution are pure and unit-testable, and so future rehoming (E17) has a
// single source of truth. Per ADR-012 §5: "Extensions" unifies Agents and
// Skills (plus Plugins and MCP) as of E17-S5; the legacy /agents and /skills
// routes now redirect to /extensions, leaving only /panels under the
// temporary "Legacy" group until it too is rehomed.

import type { Route } from "next";

/** A source of a live count badge, keyed to an existing /v2 endpoint. */
export type NavBadgeSource = "sessions" | "agents" | "skills" | "extensions";

/** One sidebar navigation entry. */
export interface ShellNavItem {
  /** Stable key used for active-state matching and React keys. */
  key: string;
  /** Route the item links to. */
  href: Route;
  /** Visible label. */
  label: string;
  /** Endpoint whose count is rendered as a badge, when one exists. */
  badge?: NavBadgeSource;
  /** When true, the item is a non-navigable stub (Extensions until E17). */
  disabled?: boolean;
}

/**
 * Primary "Workspace" nav group. Chat/Plans/Patches/Flows/Sessions/Config/
 * Extensions are all live routes. Extensions carries a live count badge
 * backed by the unified `/v2/extensions` catalog (E17-S5); Sessions carries
 * one from its own list endpoint. The others render badge-less (no backend
 * endpoints added).
 */
export const SHELL_PRIMARY_NAV: readonly ShellNavItem[] = [
  { key: "chat", href: "/", label: "Chat" },
  { key: "plans", href: "/plans" as Route, label: "Plans" },
  { key: "patches", href: "/patches" as Route, label: "Patches" },
  { key: "flows", href: "/flows" as Route, label: "Flows" },
  { key: "sessions", href: "/sessions" as Route, label: "Sessions", badge: "sessions" },
  { key: "config", href: "/config" as Route, label: "Config" },
  { key: "extensions", href: "/extensions" as Route, label: "Extensions", badge: "extensions" },
];

/**
 * Temporary "Legacy" nav group (ADR-012 §5). Agents and Skills were rehomed
 * into the Extensions hub in E17-S5; only Panels remains here until it too
 * is rehomed.
 */
export const SHELL_LEGACY_NAV: readonly ShellNavItem[] = [
  { key: "panels", href: "/panels" as Route, label: "Panels" },
];

/**
 * Resolve which nav item a pathname belongs to, for active highlighting.
 *
 * The root path maps to Chat; every other path matches the navigable item
 * with the longest href prefix (so `/sessions/abc` highlights Sessions).
 *
 * @param pathname - Current router pathname.
 * @returns The matching nav item key, defaulting to `"chat"`.
 */
export function resolveActiveNav(pathname: string): string {
  if (pathname === "/") {
    return "chat";
  }
  const candidates = [...SHELL_PRIMARY_NAV, ...SHELL_LEGACY_NAV].filter(
    (item) => !item.disabled && item.href !== "/"
  );
  const match = candidates
    .filter((item) => pathname === item.href || pathname.startsWith(`${item.href}/`))
    .sort((a, b) => String(b.href).length - String(a.href).length)[0];
  return match?.key ?? "chat";
}
