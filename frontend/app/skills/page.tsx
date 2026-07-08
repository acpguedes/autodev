"use client";

import SkillsPanel from "../../components/SkillsPanel";
import { useShellHeader } from "@/components/shell/ShellProvider";

export default function SkillsPage() {
  useShellHeader({
    title: "Skills",
    subtitle: "Deterministic skills the platform exposes for agents and operators.",
  });

  return (
    <div className="flex flex-col gap-6 p-8">
      <section className="hero-card">
        <div>
          <p className="eyebrow">Skills</p>
          <h1>Reusable agent skills</h1>
          <p className="subtitle">
            Discover the deterministic skills the platform exposes for agents and operators.
          </p>
        </div>
      </section>

      <section className="panel-card">
        <div className="panel-card__header">
          <div>
            <p className="eyebrow">Registry</p>
            <h2>Available skills</h2>
          </div>
        </div>
        <SkillsPanel />
      </section>
    </div>
  );
}
