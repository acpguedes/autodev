"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
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
    return <p className="text-sm text-ds-fg-3">{error}</p>;
  }

  if (agents.length === 0) {
    return <p className="text-sm text-ds-fg-3">Loading agents...</p>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {agents.map((agent) => (
        <Badge key={agent.name} variant="secondary">
          {agent.name}
          {agent.has_contract ? " · contract" : ""}
        </Badge>
      ))}
    </div>
  );
}

export default AgentsPanel;
