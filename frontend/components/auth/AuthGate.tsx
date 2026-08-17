"use client";

import * as React from "react";

import { getCurrentPrincipal, logoutSession, oidcLoginUrl, type AuthPrincipalV2 } from "@/lib/auth";

export interface AuthGateProps {
  /** The application content to render once a principal is resolved. */
  children: React.ReactNode;
}

/**
 * Gate the Control Center behind Control Plane authentication (E11-S2).
 *
 * Loads `GET /v2/auth/me` once on mount. Local zero-config deployments
 * resolve a principal transparently (no OIDC provider is required to see
 * the app), so this never blocks local development. When the backend
 * reports `401` — production without a valid session/credential — this
 * renders a sign-in prompt linking to the OIDC login flow instead of the
 * app content.
 *
 * @param props - The content to render once authenticated.
 * @returns The identity badge plus app content, or a sign-in prompt.
 */
export function AuthGate({ children }: AuthGateProps): React.ReactElement {
  const [status, setStatus] = React.useState<"loading" | "authenticated" | "unauthenticated">(
    "loading"
  );
  const [principal, setPrincipal] = React.useState<AuthPrincipalV2 | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    getCurrentPrincipal().then((result) => {
      if (cancelled) {
        return;
      }
      setPrincipal(result);
      setStatus(result ? "authenticated" : "unauthenticated");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (status === "loading") {
    return (
      <div role="status" aria-live="polite" data-testid="auth-gate-loading">
        Checking session…
      </div>
    );
  }

  if (status === "unauthenticated") {
    const returnTo = typeof window !== "undefined" ? window.location.pathname : "/";
    return (
      <div role="alert" data-testid="auth-gate-signin">
        <p>Sign-in required.</p>
        <a href={oidcLoginUrl(returnTo)}>Sign in</a>
      </div>
    );
  }

  return (
    <>
      {principal ? <AuthIdentityBadge principal={principal} /> : null}
      {children}
    </>
  );
}

interface AuthIdentityBadgeProps {
  principal: AuthPrincipalV2;
}

/**
 * Small identity display: subject, tenant, canonical roles, and a logout
 * action when the caller is authenticated via a revocable browser session.
 *
 * @param props - The resolved principal to display.
 * @returns The rendered identity badge.
 */
function AuthIdentityBadge({ principal }: AuthIdentityBadgeProps): React.ReactElement {
  const [loggingOut, setLoggingOut] = React.useState(false);

  const handleLogout = React.useCallback(async () => {
    setLoggingOut(true);
    try {
      await logoutSession();
      window.location.reload();
    } finally {
      setLoggingOut(false);
    }
  }, []);

  return (
    <div data-testid="auth-identity-badge">
      <span data-testid="auth-identity-subject">{principal.subject}</span>
      <span data-testid="auth-identity-tenant">{principal.tenantId}</span>
      <span data-testid="auth-identity-roles">{principal.roles.join(", ")}</span>
      {principal.authMethod === "session" ? (
        <button type="button" onClick={handleLogout} disabled={loggingOut}>
          {loggingOut ? "Signing out…" : "Sign out"}
        </button>
      ) : null}
    </div>
  );
}
