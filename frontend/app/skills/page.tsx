"use client";

import SkillsPanel from "../../components/SkillsPanel";
import { useShellHeader } from "@/components/shell/ShellProvider";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export default function SkillsPage() {
  useShellHeader({
    title: "Skills",
    subtitle: "Deterministic skills the platform exposes for agents and operators.",
  });

  return (
    <div className="flex flex-col gap-6 p-8">
      <header className="flex flex-col gap-2">
        <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">Skills</p>
        <h1 className="font-serif text-2xl font-semibold text-ds-fg">Reusable agent skills</h1>
        <p className="text-sm text-ds-fg-3">
          Discover the deterministic skills the platform exposes for agents and operators.
        </p>
      </header>

      <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
        <CardHeader>
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">Registry</p>
          <h2 className="font-serif text-lg font-semibold text-ds-fg">Available skills</h2>
        </CardHeader>
        <CardContent>
          <SkillsPanel />
        </CardContent>
      </Card>
    </div>
  );
}
