"use client";

import AgentsPanel from "../../components/AgentsPanel";
import { useShellHeader } from "@/components/shell/ShellProvider";

export default function AgentsPage() {
  useShellHeader({
    title: "Agents",
    subtitle: "The core roster plus self-registered specialized agents.",
  });

  return (
    <div className="flex flex-col gap-6 p-8">
      <section className="hero-card">
        <div>
          <p className="eyebrow">Agents</p>
          <h1>Agent registry</h1>
          <p className="subtitle">
            The core roster plus self-registered specialized agents (security, refactor, docs).
          </p>
        </div>
      </section>

      <section className="panel-card">
        <div className="panel-card__header">
          <div>
            <p className="eyebrow">Registry</p>
            <h2>Registered agents</h2>
          </div>
        </div>
        <AgentsPanel />
      </section>
    </div>
  );
}
