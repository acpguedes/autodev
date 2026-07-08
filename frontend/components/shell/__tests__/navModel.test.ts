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

  it("renders Extensions as a disabled stub and only Sessions with a badge", () => {
    const extensions = SHELL_PRIMARY_NAV.find((item) => item.key === "extensions");
    expect(extensions?.disabled).toBe(true);

    const badged = SHELL_PRIMARY_NAV.filter((item) => item.badge).map((item) => item.key);
    expect(badged).toEqual(["sessions"]);
  });

  it("keeps agents/skills/panels under the Legacy group with the expected badges", () => {
    expect(SHELL_LEGACY_NAV.map((item) => item.key)).toEqual(["agents", "skills", "panels"]);
    expect(SHELL_LEGACY_NAV.find((item) => item.key === "agents")?.badge).toBe("agents");
    expect(SHELL_LEGACY_NAV.find((item) => item.key === "skills")?.badge).toBe("skills");
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
    expect(resolveActiveNav("/agents")).toBe("agents");
    expect(resolveActiveNav("/panels")).toBe("panels");
  });

  it("falls back to Chat for unknown routes", () => {
    expect(resolveActiveNav("/does-not-exist")).toBe("chat");
  });
});
