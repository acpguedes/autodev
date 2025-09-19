"use client";

import { ReactNode } from "react";

type ChatLayoutProps = {
  sidebar: ReactNode;
  children: ReactNode;
};

export function ChatLayout({ sidebar, children }: ChatLayoutProps) {
  return (
    <div className="chat-layout">
      <aside className="chat-layout__sidebar">{sidebar}</aside>
      <main className="chat-layout__main">{children}</main>
    </div>
  );
}

export default ChatLayout;
