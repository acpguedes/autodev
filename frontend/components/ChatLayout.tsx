"use client";

import Link from "next/link";
import { ReactNode } from "react";

type ChatLayoutProps = {
  sidebar: ReactNode;
  children: ReactNode;
  currentView?: "dashboard" | "config";
};

export function ChatLayout({
  sidebar,
  children,
  currentView = "dashboard",
}: ChatLayoutProps) {
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
