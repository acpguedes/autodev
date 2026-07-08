// Pluggable UI panels — UI Extension Point contract and registry (E10-S4).
//
// Plugins contribute panels through a declarative manifest (`PanelManifest`)
// plus a React component. The registry validates the manifest, checks the
// contract version against the host, and exposes a subscribable snapshot so
// React can render panels via `useSyncExternalStore`. Enable/disable state is
// persisted (localStorage by default; injectable for tests/SSR).
//
// This module is framework-agnostic (type-only React import) so the contract
// tests run in the plain Node unit-test project.

import type { ComponentType } from "react";

/** Version of the UI Extension Point contract implemented by this host. */
export const HOST_CONTRACT_VERSION = "1.0.0";

/** Mount slots registered by the Web UI. Panels may only target these. */
export const PANEL_SLOTS = [
  "dashboard.main",
  "run.detail.sidebar",
  "session.footer",
] as const;

export type PanelSlotId = (typeof PANEL_SLOTS)[number];

export type PanelNetworkPermission = {
  /**
   * Origin allowlist for `host.fetch`, e.g. "https://api.example.com" or
   * "https://*.atlassian.net" (wildcard subdomains). Empty/absent = no egress.
   */
  egress: string[];
};

/** Least-privilege permissions. Anything not declared is denied by default. */
export type PanelPermissions = {
  network?: PanelNetworkPermission;
};

export type PanelManifest = {
  /** Unique id, `<publisher>/<name>` — e.g. "acme/coder-plus.panel". */
  id: string;
  /** Human-readable title rendered in the panel chrome. */
  title: string;
  /** Registered slot where the panel mounts. */
  slot: PanelSlotId;
  /** SemVer range against `HOST_CONTRACT_VERSION`, e.g. "^1.0". */
  contract: string;
  description?: string;
  permissions?: PanelPermissions;
};

/** Capabilities the host grants to a panel (gated by its permissions). */
export type PanelHost = {
  panelId: string;
  hostVersion: string;
  /** Network access restricted to the manifest's egress allowlist. */
  fetch: (url: string, init?: RequestInit) => Promise<Response>;
};

export type PanelProps = {
  manifest: PanelManifest;
  host: PanelHost;
};

export type PanelComponent = ComponentType<PanelProps>;

export type PanelRegistration = {
  manifest: PanelManifest;
  Component: PanelComponent;
  /** Contributor: plugin id (Plugin Host) or "builtin". */
  source?: string;
};

export type RegisteredPanel = PanelRegistration & { enabled: boolean };

export type ManifestValidation =
  | { ok: true; manifest: PanelManifest }
  | { ok: false; errors: string[] };

export type RegisterResult = { ok: true } | { ok: false; errors: string[] };

const ID_PATTERN = /^[a-z0-9][a-z0-9-]*\/[a-z0-9][a-z0-9.-]*$/;

const parseVersion = (value: string): [number, number] | null => {
  const match = /^(\d+)\.(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!match) {
    return null;
  }
  return [Number(match[1]), Number(match[2])];
};

/**
 * Checks a manifest `contract` range against the host contract version.
 * Supports exact ("1.0") and caret ("^1.0") ranges: caret requires the same
 * major and a host minor >= the requested minor.
 */
export function isContractCompatible(
  range: string,
  hostVersion: string = HOST_CONTRACT_VERSION
): boolean {
  const host = parseVersion(hostVersion);
  if (!host) {
    return false;
  }
  const trimmed = range.trim();
  const caret = trimmed.startsWith("^");
  const requested = parseVersion(caret ? trimmed.slice(1) : trimmed);
  if (!requested) {
    return false;
  }
  if (requested[0] !== host[0]) {
    return false;
  }
  return caret ? host[1] >= requested[1] : host[1] === requested[1];
}

/** Structural validation of an untrusted manifest (plugin-supplied). */
export function validatePanelManifest(input: unknown): ManifestValidation {
  if (typeof input !== "object" || input === null) {
    return { ok: false, errors: ["manifest must be an object"] };
  }
  const manifest = input as Record<string, unknown>;
  const errors: string[] = [];

  if (typeof manifest.id !== "string" || !ID_PATTERN.test(manifest.id)) {
    errors.push('"id" must match "<publisher>/<name>", e.g. "acme/coder-plus.panel"');
  }
  if (typeof manifest.title !== "string" || manifest.title.trim() === "") {
    errors.push('"title" must be a non-empty string');
  }
  if (
    typeof manifest.slot !== "string" ||
    !(PANEL_SLOTS as readonly string[]).includes(manifest.slot)
  ) {
    errors.push(`"slot" must be one of: ${PANEL_SLOTS.join(", ")}`);
  }
  if (
    typeof manifest.contract !== "string" ||
    parseVersion(
      manifest.contract.trim().startsWith("^")
        ? manifest.contract.trim().slice(1)
        : manifest.contract
    ) === null
  ) {
    errors.push('"contract" must be a SemVer range like "^1.0"');
  }
  if (manifest.description !== undefined && typeof manifest.description !== "string") {
    errors.push('"description" must be a string when present');
  }
  if (manifest.permissions !== undefined) {
    const permissions = manifest.permissions as Record<string, unknown> | null;
    if (typeof permissions !== "object" || permissions === null) {
      errors.push('"permissions" must be an object when present');
    } else if (permissions.network !== undefined) {
      const network = permissions.network as Record<string, unknown> | null;
      const egress =
        typeof network === "object" && network !== null ? network.egress : undefined;
      if (
        !Array.isArray(egress) ||
        egress.some((entry) => typeof entry !== "string" || !/^https?:\/\//.test(entry))
      ) {
        errors.push(
          '"permissions.network.egress" must be an array of http(s) origin patterns'
        );
      }
    }
  }

  if (errors.length > 0) {
    return { ok: false, errors };
  }
  return { ok: true, manifest: input as PanelManifest };
}

export type PanelStateStorage = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
};

export type PanelRegistry = {
  register(registration: PanelRegistration): RegisterResult;
  unregister(id: string): void;
  get(id: string): RegisteredPanel | undefined;
  list(): RegisteredPanel[];
  /** Enabled panels for a slot, in registration order. */
  getForSlot(slot: PanelSlotId): RegisteredPanel[];
  setEnabled(id: string, enabled: boolean): void;
  subscribe(listener: () => void): () => void;
  /** Monotonic version for `useSyncExternalStore`. */
  getSnapshot(): number;
};

const STORAGE_KEY = "autodev.panels.disabled";

const defaultStorage = (): PanelStateStorage | null =>
  typeof window !== "undefined" ? window.localStorage : null;

export function createPanelRegistry(
  options: { hostVersion?: string; storage?: PanelStateStorage | null } = {}
): PanelRegistry {
  const hostVersion = options.hostVersion ?? HOST_CONTRACT_VERSION;
  const storage = options.storage === undefined ? defaultStorage() : options.storage;

  const panels = new Map<string, PanelRegistration>();
  const listeners = new Set<() => void>();
  let version = 0;

  const loadDisabled = (): Set<string> => {
    if (!storage) {
      return new Set();
    }
    try {
      const raw = storage.getItem(STORAGE_KEY);
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      return new Set(
        Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === "string") : []
      );
    } catch {
      return new Set();
    }
  };

  const disabled = loadDisabled();

  const persistDisabled = () => {
    if (!storage) {
      return;
    }
    try {
      storage.setItem(STORAGE_KEY, JSON.stringify(Array.from(disabled)));
    } catch {
      // Persistence is best-effort; state still applies for the session.
    }
  };

  const notify = () => {
    version += 1;
    Array.from(listeners).forEach((listener) => listener());
  };

  const toRegistered = (registration: PanelRegistration): RegisteredPanel => ({
    ...registration,
    enabled: !disabled.has(registration.manifest.id),
  });

  return {
    register(registration) {
      const validated = validatePanelManifest(registration.manifest);
      if (!validated.ok) {
        return { ok: false, errors: validated.errors };
      }
      const { manifest } = validated;
      if (!isContractCompatible(manifest.contract, hostVersion)) {
        return {
          ok: false,
          errors: [
            `contract "${manifest.contract}" is not compatible with host ${hostVersion}`,
          ],
        };
      }
      if (panels.has(manifest.id)) {
        return { ok: false, errors: [`panel "${manifest.id}" is already registered`] };
      }
      panels.set(manifest.id, registration);
      notify();
      return { ok: true };
    },
    unregister(id) {
      if (panels.delete(id)) {
        notify();
      }
    },
    get(id) {
      const registration = panels.get(id);
      return registration ? toRegistered(registration) : undefined;
    },
    list() {
      return Array.from(panels.values()).map(toRegistered);
    },
    getForSlot(slot) {
      return Array.from(panels.values())
        .filter(
          (registration) =>
            registration.manifest.slot === slot && !disabled.has(registration.manifest.id)
        )
        .map(toRegistered);
    },
    setEnabled(id, enabled) {
      const changed = enabled ? disabled.delete(id) : !disabled.has(id) && !!disabled.add(id);
      if (changed) {
        persistDisabled();
        notify();
      }
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot() {
      return version;
    },
  };
}

/** Shared registry used by the Web UI. */
export const panelRegistry = createPanelRegistry();
