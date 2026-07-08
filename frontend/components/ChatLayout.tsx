"use client";

import { ReactNode } from "react";

/**
 * Deprecated content wrapper, retained only until E15-S3 removes it.
 *
 * As of E15-S2 the Execution Control Center shell (`components/shell`) owns the
 * sidebar rail, contextual header, and execution panel, so this component no
 * longer renders any shell chrome or navigation and its former `layoutMode`
 * ("sidebar"/"focus") switch is gone. It now renders its children directly,
 * with an optional inline aside, so no remaining call site breaks before the
 * component is deleted.
 */
type ChatLayoutProps = {
  /** Optional supplementary content rendered ahead of the children. */
  sidebar?: ReactNode;
  /** Page body. */
  children: ReactNode;
};

/**
 * Render page content within the shell's main region.
 *
 * @param props - Optional inline aside and the page body.
 * @returns The wrapped content.
 */
export function ChatLayout({ sidebar, children }: ChatLayoutProps) {
  return (
    <div className="flex flex-col gap-6 p-8">
      {sidebar}
      {children}
    </div>
  );
}

export default ChatLayout;
