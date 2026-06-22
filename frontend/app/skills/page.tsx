"use client";

import ChatLayout from "../../components/ChatLayout";
import SkillsPanel from "../../components/SkillsPanel";

export default function SkillsPage() {
  return (
    <ChatLayout currentView="dashboard">
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
    </ChatLayout>
  );
}
