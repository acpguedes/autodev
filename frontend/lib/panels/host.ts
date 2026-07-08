// Panel sandbox (E10-S4-T2): the host API handed to plugin panels.
//
// Panels never receive raw platform capabilities. They get a `PanelHost`
// whose surface is gated by the permissions declared in their manifest —
// least privilege, deny by default. Today that covers network egress; new
// capabilities must follow the same pattern.

import {
  HOST_CONTRACT_VERSION,
  type PanelHost,
  type PanelManifest,
} from "./registry";

export class PanelPermissionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PanelPermissionError";
  }
}

const matchesPattern = (target: URL, pattern: string): boolean => {
  const wildcard = pattern.includes("://*.");
  let base: URL;
  try {
    base = new URL(wildcard ? pattern.replace("://*.", "://") : pattern);
  } catch {
    return false;
  }
  if (base.protocol !== target.protocol || base.port !== target.port) {
    return false;
  }
  if (wildcard) {
    return (
      target.hostname === base.hostname || target.hostname.endsWith(`.${base.hostname}`)
    );
  }
  return target.hostname === base.hostname;
};

/** True when `url` is an http(s) URL whose origin matches the allowlist. */
export function isEgressAllowed(url: string, allowlist: string[]): boolean {
  let target: URL;
  try {
    target = new URL(url);
  } catch {
    return false;
  }
  if (target.protocol !== "https:" && target.protocol !== "http:") {
    return false;
  }
  return allowlist.some((pattern) => matchesPattern(target, pattern));
}

/** Builds the permission-gated host API for a panel. */
export function createPanelHost(
  manifest: PanelManifest,
  options: { fetchImpl?: typeof fetch } = {}
): PanelHost {
  const fetchImpl =
    options.fetchImpl ?? (typeof fetch !== "undefined" ? fetch : undefined);

  return {
    panelId: manifest.id,
    hostVersion: HOST_CONTRACT_VERSION,
    fetch: async (url, init) => {
      const allowlist = manifest.permissions?.network?.egress ?? [];
      if (!isEgressAllowed(url, allowlist)) {
        throw new PanelPermissionError(
          `panel "${manifest.id}" has no network permission for ${url}; ` +
            "declare the origin under permissions.network.egress"
        );
      }
      if (!fetchImpl) {
        throw new Error("fetch is not available in this environment");
      }
      return fetchImpl(url, init);
    },
  };
}
