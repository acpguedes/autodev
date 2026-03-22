"use client";

import Link from "next/link";
import { ReactNode } from "react";

type ChatLayoutProps = {
  sidebar?: ReactNode;
  children: ReactNode;
  currentView?: "dashboard" | "config";
  layoutMode?: "sidebar" | "focus";
};

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
          <div className="sidebar-brand">
            <p className="eyebrow">AutoDev Architect</p>
            <h1>Control Center</h1>
          </div>

          <nav className="sidebar-nav" aria-label="Primary">
            <Link
              className={`sidebar-nav__link ${
                currentView === "dashboard" ? "sidebar-nav__link--active" : ""
              }`}
              href="/"
            >
              Dashboard
            </Link>
            <Link
              className={`sidebar-nav__link ${
                currentView === "config" ? "sidebar-nav__link--active" : ""
              }`}
              href="/config"
            >
              Config
            </Link>
          </nav>

          {sidebar}
        </div>
      </aside>
      <main className="chat-layout__main">{children}</main>
    </div>
  );
}

export default ChatLayout;
