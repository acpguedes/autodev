"use client";

import { useEffect, useState } from "react";

import { listAgents, type AgentSummary } from "../lib/api_ext";

export function AgentsPanel() {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAgents()
      .then(setAgents)
      .catch(() => setError("Agents endpoint unavailable. Start the backend to load agents."));
  }, []);

  if (error) {
    return <p className="empty-state">{error}</p>;
  }

  if (agents.length === 0) {
    return <p className="empty-state">Loading agents...</p>;
  }

  return (
    <div className="tag-list">
      {agents.map((agent) => (
        <span className="tag" key={agent.name}>
          {agent.name}
          {agent.has_contract ? " · contract" : ""}
        </span>
      ))}
    </div>
  );
}

export default AgentsPanel;
