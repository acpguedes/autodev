// Browser client for the Control Plane's authenticated identity (E11-S2).
//
// Local zero-config deployments are transparent: `getCurrentPrincipal()`
// still resolves (to the local owner principal) with no OIDC provider
// configured, so this module never has to special-case "auth is off".

import { buildUrl, requestJson } from "./api_ext";

/** Canonical roles, mirroring `backend.auth.contracts.Role`. */
export type AuthRoleV2 = "owner" | "admin" | "maintainer" | "operator" | "viewer";

/** The authenticated caller's identity, as returned by `GET /v2/auth/me`. */
export type AuthPrincipalV2 = {
  subject: string;
  tenantId: string;
  roles: AuthRoleV2[];
  scopes: string[];
  authMethod: "local" | "legacy_pat" | "oidc" | "service_key" | "session";
};

/**
 * Fetch the calling principal's identity, roles, and effective scopes.
 *
 * @returns The principal, or `null` when the caller is unauthenticated
 *   (production without a session/credential) or the backend cannot be
 *   reached.
 */
export async function getCurrentPrincipal(): Promise<AuthPrincipalV2 | null> {
  try {
    return await requestJson<AuthPrincipalV2>("/v2/auth/me");
  } catch {
    return null;
  }
}

/**
 * Build the URL that starts an OIDC authorization-code + PKCE login.
 *
 * @param returnTo - Relative path to return to after a successful login.
 * @returns The absolute `/v2/auth/oidc/login` URL, including `returnTo`.
 */
export function oidcLoginUrl(returnTo: string): string {
  const safeReturnTo = returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/";
  return buildUrl(`/v2/auth/oidc/login?returnTo=${encodeURIComponent(safeReturnTo)}`);
}

/**
 * Log out the current browser session.
 *
 * A no-op-equivalent (resolves without throwing) when there is no active
 * session to revoke — e.g. local zero-config or a service-key caller.
 */
export async function logoutSession(): Promise<void> {
  const response = await fetch(buildUrl("/v2/auth/session"), {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 400) {
    throw new Error(`Logout failed (${response.status})`);
  }
}
