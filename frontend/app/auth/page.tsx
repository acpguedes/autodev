"use client";

import { useEffect, useState } from "react";

import { useShellHeader } from "@/components/shell/ShellProvider";
import { getCurrentPrincipal, logoutSession, oidcLoginUrl, type AuthPrincipalV2 } from "@/lib/auth";

/**
 * Account page: shows the authenticated principal's identity, roles, and
 * effective scopes, and offers sign-in/sign-out (E11-S2).
 *
 * @returns The rendered account screen.
 */
export default function AuthPage() {
  useShellHeader({
    title: "Account",
    subtitle: "Your Control Plane identity, roles, and session.",
  });

  const [status, setStatus] = useState<"loading" | "authenticated" | "unauthenticated">(
    "loading"
  );
  const [principal, setPrincipal] = useState<AuthPrincipalV2 | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
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

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await logoutSession();
      window.location.reload();
    } finally {
      setLoggingOut(false);
    }
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-col gap-2">
        <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">
          Control Plane
        </p>
        <h2 className="font-serif text-2xl font-semibold text-ds-fg">Account</h2>
      </header>

      {status === "loading" ? <p className="text-sm text-ds-fg-3">Loading…</p> : null}

      {status === "unauthenticated" ? (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-ds-fg-3">You are not signed in.</p>
          <a
            href={oidcLoginUrl("/auth")}
            className="w-fit rounded-md bg-ds-accent px-4 py-2 text-sm font-medium text-ds-bg"
          >
            Sign in
          </a>
        </div>
      ) : null}

      {status === "authenticated" && principal ? (
        <dl className="flex flex-col gap-3 text-sm">
          <div>
            <dt className="text-ds-fg-3">Subject</dt>
            <dd className="text-ds-fg">{principal.subject}</dd>
          </div>
          <div>
            <dt className="text-ds-fg-3">Tenant</dt>
            <dd className="text-ds-fg">{principal.tenantId}</dd>
          </div>
          <div>
            <dt className="text-ds-fg-3">Roles</dt>
            <dd className="text-ds-fg">{principal.roles.join(", ")}</dd>
          </div>
          <div>
            <dt className="text-ds-fg-3">Auth method</dt>
            <dd className="text-ds-fg">{principal.authMethod}</dd>
          </div>
          {principal.authMethod === "session" ? (
            <button
              type="button"
              onClick={handleLogout}
              disabled={loggingOut}
              className="w-fit rounded-md border border-ds-border px-4 py-2 text-sm font-medium text-ds-fg"
            >
              {loggingOut ? "Signing out…" : "Sign out"}
            </button>
          ) : null}
        </dl>
      ) : null}
    </div>
  );
}
