// Contract tests for the UI Extension Point (E10-S4 DoD).

import { describe, expect, it, vi } from "vitest";

import { installPluginPanels } from "../discovery";
import { createPanelHost, isEgressAllowed, PanelPermissionError } from "../host";
import {
  createPanelRegistry,
  isContractCompatible,
  validatePanelManifest,
  HOST_CONTRACT_VERSION,
  type PanelComponent,
  type PanelManifest,
  type PanelStateStorage,
} from "../registry";

const Dummy: PanelComponent = () => null;

const manifest = (overrides: Partial<PanelManifest> = {}): PanelManifest => ({
  id: "acme/coder-plus.panel",
  title: "Coder+ panel",
  slot: "run.detail.sidebar",
  contract: "^1.0",
  ...overrides,
});

const memoryStorage = (): PanelStateStorage => {
  const store = new Map<string, string>();
  return {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => {
      store.set(key, value);
    },
  };
};

describe("contract version compatibility", () => {
  it("accepts ranges satisfied by the host contract", () => {
    expect(HOST_CONTRACT_VERSION).toBe("1.0.0");
    expect(isContractCompatible("^1.0")).toBe(true);
    expect(isContractCompatible("1.0")).toBe(true);
    expect(isContractCompatible("^1.0.0")).toBe(true);
  });

  it("rejects incompatible or malformed ranges", () => {
    expect(isContractCompatible("^2.0")).toBe(false);
    expect(isContractCompatible("^1.1")).toBe(false);
    expect(isContractCompatible("0.9")).toBe(false);
    expect(isContractCompatible("banana")).toBe(false);
  });
});

describe("manifest validation", () => {
  it("accepts a well-formed manifest", () => {
    const result = validatePanelManifest(
      manifest({
        description: "desc",
        permissions: { network: { egress: ["https://*.atlassian.net"] } },
      })
    );
    expect(result.ok).toBe(true);
  });

  it("rejects malformed manifests with actionable errors", () => {
    const result = validatePanelManifest({
      id: "Not Valid",
      title: "",
      slot: "nope",
      contract: "latest",
      permissions: { network: { egress: ["ftp://x"] } },
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.join("\n")).toContain('"id"');
      expect(result.errors.join("\n")).toContain('"title"');
      expect(result.errors.join("\n")).toContain('"slot"');
      expect(result.errors.join("\n")).toContain('"contract"');
      expect(result.errors.join("\n")).toContain("egress");
    }
  });

  it("rejects non-object input", () => {
    expect(validatePanelManifest(null).ok).toBe(false);
    expect(validatePanelManifest("panel").ok).toBe(false);
  });
});

describe("panel registry", () => {
  it("registers, lists and unregisters panels", () => {
    const registry = createPanelRegistry({ storage: null });
    expect(registry.register({ manifest: manifest(), Component: Dummy })).toEqual({
      ok: true,
    });
    expect(registry.list()).toHaveLength(1);
    expect(registry.get("acme/coder-plus.panel")?.enabled).toBe(true);
    registry.unregister("acme/coder-plus.panel");
    expect(registry.list()).toHaveLength(0);
  });

  it("rejects duplicate ids and incompatible contracts", () => {
    const registry = createPanelRegistry({ storage: null });
    registry.register({ manifest: manifest(), Component: Dummy });
    const duplicate = registry.register({ manifest: manifest(), Component: Dummy });
    expect(duplicate.ok).toBe(false);
    if (!duplicate.ok) {
      expect(duplicate.errors[0]).toContain("already registered");
    }
    const incompatible = registry.register({
      manifest: manifest({ id: "acme/other.panel", contract: "^2.0" }),
      Component: Dummy,
    });
    expect(incompatible.ok).toBe(false);
    if (!incompatible.ok) {
      expect(incompatible.errors[0]).toContain("not compatible");
    }
  });

  it("filters slots by enablement", () => {
    const registry = createPanelRegistry({ storage: null });
    registry.register({ manifest: manifest(), Component: Dummy });
    registry.register({
      manifest: manifest({ id: "acme/dash.panel", slot: "dashboard.main" }),
      Component: Dummy,
    });
    expect(registry.getForSlot("run.detail.sidebar")).toHaveLength(1);
    expect(registry.getForSlot("dashboard.main")).toHaveLength(1);
    expect(registry.getForSlot("session.footer")).toHaveLength(0);

    registry.setEnabled("acme/coder-plus.panel", false);
    expect(registry.getForSlot("run.detail.sidebar")).toHaveLength(0);
    expect(registry.get("acme/coder-plus.panel")?.enabled).toBe(false);
    expect(registry.list()).toHaveLength(2);

    registry.setEnabled("acme/coder-plus.panel", true);
    expect(registry.getForSlot("run.detail.sidebar")).toHaveLength(1);
  });

  it("persists enablement across registry instances", () => {
    const storage = memoryStorage();
    const first = createPanelRegistry({ storage });
    first.register({ manifest: manifest(), Component: Dummy });
    first.setEnabled("acme/coder-plus.panel", false);

    const second = createPanelRegistry({ storage });
    second.register({ manifest: manifest(), Component: Dummy });
    expect(second.get("acme/coder-plus.panel")?.enabled).toBe(false);
  });

  it("notifies subscribers on changes", () => {
    const registry = createPanelRegistry({ storage: null });
    const listener = vi.fn();
    const unsubscribe = registry.subscribe(listener);
    const before = registry.getSnapshot();
    registry.register({ manifest: manifest(), Component: Dummy });
    registry.setEnabled("acme/coder-plus.panel", false);
    expect(listener).toHaveBeenCalledTimes(2);
    expect(registry.getSnapshot()).toBeGreaterThan(before);
    unsubscribe();
    registry.setEnabled("acme/coder-plus.panel", true);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

describe("panel host sandbox", () => {
  it("denies network access by default", async () => {
    const host = createPanelHost(manifest(), { fetchImpl: vi.fn() });
    await expect(host.fetch("https://api.example.com/runs")).rejects.toBeInstanceOf(
      PanelPermissionError
    );
  });

  it("allows only allowlisted origins", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true } as Response);
    const host = createPanelHost(
      manifest({
        permissions: {
          network: { egress: ["https://api.example.com", "https://*.atlassian.net"] },
        },
      }),
      { fetchImpl: fetchImpl as unknown as typeof fetch }
    );
    await expect(host.fetch("https://api.example.com/runs")).resolves.toEqual({
      ok: true,
    });
    await expect(host.fetch("https://acme.atlassian.net/rest")).resolves.toEqual({
      ok: true,
    });
    await expect(host.fetch("https://evil.example.net/")).rejects.toBeInstanceOf(
      PanelPermissionError
    );
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("matches egress patterns strictly", () => {
    const allowlist = ["https://*.atlassian.net", "https://api.example.com"];
    expect(isEgressAllowed("https://foo.atlassian.net/x", allowlist)).toBe(true);
    expect(isEgressAllowed("https://atlassian.net/x", allowlist)).toBe(true);
    expect(isEgressAllowed("https://not-atlassian.example/x", allowlist)).toBe(false);
    expect(isEgressAllowed("http://api.example.com/", allowlist)).toBe(false);
    expect(isEgressAllowed("ftp://api.example.com/", allowlist)).toBe(false);
    expect(isEgressAllowed("not a url", allowlist)).toBe(false);
  });
});

describe("plugin host discovery", () => {
  it("installs valid panels and isolates failures without throwing", () => {
    const registry = createPanelRegistry({ storage: null });
    const report = installPluginPanels(registry, [
      {
        pluginId: "acme/plugin-jira",
        hostApi: "^1.0",
        panels: [
          { manifest: manifest({ id: "acme/plugin-jira.panel" }), Component: Dummy },
          { manifest: { id: "broken" }, Component: Dummy },
        ],
      },
      {
        pluginId: "acme/plugin-future",
        hostApi: "^2.0",
        panels: [
          { manifest: manifest({ id: "acme/plugin-future.panel" }), Component: Dummy },
        ],
      },
    ]);

    expect(report.installed).toBe(1);
    expect(report.rejected).toBe(2);
    expect(registry.list().map((panel) => panel.manifest.id)).toEqual([
      "acme/plugin-jira.panel",
    ]);
    expect(registry.get("acme/plugin-jira.panel")?.source).toBe("acme/plugin-jira");
    const futureEntry = report.entries.find(
      (entry) => entry.pluginId === "acme/plugin-future"
    );
    expect(futureEntry?.errors[0]).toContain("hostApi");
  });
});
