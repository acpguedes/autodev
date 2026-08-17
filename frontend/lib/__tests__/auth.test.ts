import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getCurrentPrincipal, logoutSession, oidcLoginUrl } from "../auth";

function mockJsonResponse(body: unknown, init?: { status?: number; ok?: boolean }): void {
  const status = init?.status ?? 200;
  const ok = init?.ok ?? true;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      status,
      json: async () => body,
      text: async () => JSON.stringify(body),
    })
  );
}

describe("auth.ts", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends browser credentials on JSON requests", async () => {
    mockJsonResponse({
      subject: "u",
      tenantId: "t",
      roles: ["viewer"],
      scopes: [],
      authMethod: "session",
    });

    await getCurrentPrincipal();

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v2/auth/me"),
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("returns the decoded principal on success", async () => {
    const principal = {
      subject: "u",
      tenantId: "t",
      roles: ["viewer"],
      scopes: [],
      authMethod: "session",
    };
    mockJsonResponse(principal);

    await expect(getCurrentPrincipal()).resolves.toEqual(principal);
  });

  it("returns null instead of throwing when unauthenticated", async () => {
    mockJsonResponse({ detail: "unauthenticated" }, { status: 401, ok: false });

    await expect(getCurrentPrincipal()).resolves.toBeNull();
  });

  it("builds an absolute oidc login url carrying returnTo", () => {
    const url = oidcLoginUrl("/dashboard");
    expect(url).toContain("/v2/auth/oidc/login");
    expect(url).toContain(`returnTo=${encodeURIComponent("/dashboard")}`);
  });

  it("rejects an absolute returnTo in favor of the root path", () => {
    const url = oidcLoginUrl("https://evil.example.com/");
    expect(url).toContain(`returnTo=${encodeURIComponent("/")}`);
  });

  it("sends credentials when logging out", async () => {
    mockJsonResponse({}, { status: 204 });

    await logoutSession();

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v2/auth/session"),
      expect.objectContaining({ method: "DELETE", credentials: "include" })
    );
  });
});
