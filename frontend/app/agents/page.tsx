"use client";

import AgentsPanel from "../../components/AgentsPanel";
import { useShellHeader } from "@/components/shell/ShellProvider";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export default function AgentsPage() {
  useShellHeader({
    title: "Agents",
    subtitle: "The core roster plus self-registered specialized agents.",
  });

  return (
    <div className="flex flex-col gap-6 p-8">
      <header className="flex flex-col gap-2">
        <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">Agents</p>
        <h1 className="font-serif text-2xl font-semibold text-ds-fg">Agent registry</h1>
        <p className="text-sm text-ds-fg-3">
          The core roster plus self-registered specialized agents (security, refactor, docs).
        </p>
      </header>

      <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
        <CardHeader>
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">Registry</p>
          <h2 className="font-serif text-lg font-semibold text-ds-fg">Registered agents</h2>
        </CardHeader>
        <CardContent>
          <AgentsPanel />
        </CardContent>
      </Card>
    </div>
  );
}
