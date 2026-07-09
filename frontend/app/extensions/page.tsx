"use client";

import { ExtensionsHub } from "@/components/extensions/ExtensionsHub";
import { useShellHeader } from "@/components/shell/ShellProvider";

/**
 * Extensions hub screen (E17-S5): the unified home for Agents, Skills,
 * Plugins, and MCP exposures, replacing the standalone `/agents` and
 * `/skills` routes (ADR-012 §5). Publishes the contextual header via the
 * E15 App Shell and renders the tabbed catalog as routed content.
 *
 * @returns The extensions hub page.
 */
export default function ExtensionsPage() {
  useShellHeader({
    title: "Extensions",
    subtitle: "Agents, skills, plugins, and MCP exposures registered with the control plane.",
  });

  return (
    <div className="flex flex-col gap-6 p-8">
      <ExtensionsHub />
    </div>
  );
}
