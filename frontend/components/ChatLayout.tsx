"use client";

import Link from "next/link";
import type { Route } from "next";
import { ReactNode } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";

type ChatLayoutProps = {
  sidebar?: ReactNode;
  children: ReactNode;
  currentView?:
    | "dashboard"
    | "sessions"
    | "config"
    | "agents"
    | "plans"
    | "flows"
    | "skills"
    | "patches"
    | "panels";
  layoutMode?: "sidebar" | "focus";
};

const NAV_ITEMS: Array<{ view: ChatLayoutProps["currentView"]; href: Route; label: string }> = [
  { view: "dashboard", href: "/", label: "Dashboard" },
  { view: "sessions", href: "/sessions", label: "Sessions" },
  { view: "config", href: "/config", label: "Config" },
  { view: "agents", href: "/agents", label: "Agents" },
  { view: "plans", href: "/plans", label: "Plans" },
  { view: "flows", href: "/flows", label: "Flows" },
  { view: "skills", href: "/skills", label: "Skills" },
  { view: "patches", href: "/patches", label: "Patches" },
  { view: "panels", href: "/panels" as Route, label: "Panels" },
];

export function ChatLayout({
  sidebar,
  children,
  currentView = "dashboard",
  layoutMode = "sidebar",
}: ChatLayoutProps) {
  if (layoutMode === "focus") {
    return (
      <div className="chat-layout chat-layout--focus">
        <header className="chat-topbar">
          <div className="chat-topbar__brand">
            <p className="eyebrow">AutoDev Architect</p>
            <h1>Chat workspace</h1>
          </div>

          <nav className="chat-topbar__nav" aria-label="Primary">
            <Link className="secondary-button secondary-button--link" href="/config">
              Configuração
            </Link>
            <ThemeToggle />
          </nav>
        </header>
        <main className="chat-layout__main">{children}</main>
      </div>
    );
  }

  return (
    <div className="chat-layout">
      <aside className="chat-layout__sidebar">
        <div className="sidebar-shell">
          <div className="sidebar-brand" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.75rem" }}>
            <div>
              <p className="eyebrow">AutoDev Architect</p>
              <h1>Control Center</h1>
            </div>
            <ThemeToggle />
          </div>

          <nav className="sidebar-nav" aria-label="Primary">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                className={`sidebar-nav__link ${
                  currentView === item.view ? "sidebar-nav__link--active" : ""
                }`}
                href={item.href}
              >
                {item.label}
              </Link>
            ))}
          </nav>

          {sidebar}
        </div>
      </aside>
      <main className="chat-layout__main">{children}</main>
    </div>
  );
}

export default ChatLayout;
