import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthGate } from "../AuthGate";

vi.mock("@/lib/auth", () => ({
  getCurrentPrincipal: vi.fn(),
  oidcLoginUrl: (returnTo: string) => `/v2/auth/oidc/login?returnTo=${encodeURIComponent(returnTo)}`,
  logoutSession: vi.fn(),
}));

import { getCurrentPrincipal } from "@/lib/auth";

describe("AuthGate", () => {
  afterEach(() => {
    cleanup();
    vi.mocked(getCurrentPrincipal).mockReset();
  });

  it("renders children transparently once a principal resolves (local zero-config)", async () => {
    vi.mocked(getCurrentPrincipal).mockResolvedValue({
      subject: "local",
      tenantId: "default",
      roles: ["owner"],
      scopes: [],
      authMethod: "local",
    });

    render(
      <AuthGate>
        <div data-testid="app-content">app content</div>
      </AuthGate>
    );

    await waitFor(() => expect(screen.getByTestId("app-content")).toBeTruthy());
    expect(screen.getByTestId("auth-identity-subject").textContent).toBe("local");
    expect(screen.getByTestId("auth-identity-tenant").textContent).toBe("default");
  });

  it("shows a sign-in prompt linking to OIDC login when unauthenticated", async () => {
    vi.mocked(getCurrentPrincipal).mockResolvedValue(null);

    render(
      <AuthGate>
        <div data-testid="app-content">app content</div>
      </AuthGate>
    );

    await waitFor(() => expect(screen.getByTestId("auth-gate-signin")).toBeTruthy());
    expect(screen.queryByTestId("app-content")).toBeNull();
    const link = screen.getByText("Sign in") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toContain("/v2/auth/oidc/login");
  });

  it("shows a sign-out control only for session-authenticated principals", async () => {
    vi.mocked(getCurrentPrincipal).mockResolvedValue({
      subject: "user-1",
      tenantId: "tenant-a",
      roles: ["maintainer"],
      scopes: [],
      authMethod: "session",
    });

    render(
      <AuthGate>
        <div>app content</div>
      </AuthGate>
    );

    await waitFor(() => expect(screen.getByText("Sign out")).toBeTruthy());
  });

  it("does not show a sign-out control for a service-key caller", async () => {
    vi.mocked(getCurrentPrincipal).mockResolvedValue({
      subject: "ci",
      tenantId: "tenant-a",
      roles: ["operator"],
      scopes: [],
      authMethod: "service_key",
    });

    render(
      <AuthGate>
        <div data-testid="app-content">app content</div>
      </AuthGate>
    );

    await waitFor(() => expect(screen.getByTestId("app-content")).toBeTruthy());
    expect(screen.queryByText("Sign out")).toBeNull();
  });
});
