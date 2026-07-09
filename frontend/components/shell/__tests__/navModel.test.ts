// Unit tests for the sidebar navigation model (E15-S2): the item set the rail
// renders and how the active item is resolved from the current pathname. The
// rail's rendered landmarks and badges are asserted by the Playwright e2e.

import { describe, expect, it } from "vitest";

import {
  SHELL_LEGACY_NAV,
  SHELL_PRIMARY_NAV,
  resolveActiveNav,
} from "../navModel";

describe("nav model", () => {
  it("exposes the primary Workspace group per ADR-012 §5", () => {
    expect(SHELL_PRIMARY_NAV.map((item) => item.key)).toEqual([
      "chat",
      "plans",
      "patches",
      "flows",
      "sessions",
      "config",
      "extensions",
    ]);
  });

  it("renders Extensions as an enabled item with a live badge, alongside Sessions", () => {
    const extensions = SHELL_PRIMARY_NAV.find((item) => item.key === "extensions");
    expect(extensions?.disabled).toBeFalsy();
    expect(extensions?.badge).toBe("extensions");

    const badged = SHELL_PRIMARY_NAV.filter((item) => item.badge).map((item) => item.key);
    expect(badged).toEqual(["sessions", "extensions"]);
  });

  it("keeps only Panels under the Legacy group, now that agents/skills moved to Extensions", () => {
    expect(SHELL_LEGACY_NAV.map((item) => item.key)).toEqual(["panels"]);
    expect(SHELL_LEGACY_NAV.find((item) => item.key === "panels")?.badge).toBeUndefined();
  });
});

describe("resolveActiveNav", () => {
  it("maps the root path to Chat", () => {
    expect(resolveActiveNav("/")).toBe("chat");
  });

  it("matches exact and nested routes by the longest href prefix", () => {
    expect(resolveActiveNav("/plans")).toBe("plans");
    expect(resolveActiveNav("/sessions")).toBe("sessions");
    expect(resolveActiveNav("/sessions/abc-123")).toBe("sessions");
    expect(resolveActiveNav("/extensions")).toBe("extensions");
    expect(resolveActiveNav("/panels")).toBe("panels");
  });

  it("falls back to Chat for unknown routes, including the redirect-only legacy /agents and /skills paths", () => {
    expect(resolveActiveNav("/does-not-exist")).toBe("chat");
    expect(resolveActiveNav("/agents")).toBe("chat");
    expect(resolveActiveNav("/skills")).toBe("chat");
  });
});
