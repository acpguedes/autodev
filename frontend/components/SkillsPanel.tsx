"use client";

import { useEffect, useState } from "react";

import { listSkills, type SkillSummary } from "../lib/api_ext";

export function SkillsPanel() {
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listSkills()
      .then(setSkills)
      .catch(() => setError("Skills endpoint unavailable. Start the backend to load skills."));
  }, []);

  if (error) {
    return <p className="empty-state">{error}</p>;
  }

  if (skills.length === 0) {
    return <p className="empty-state">Loading skills...</p>;
  }

  return (
    <ul className="note-list">
      {skills.map((skill) => (
        <li key={skill.name}>
          <strong>{skill.name}</strong> — {skill.description}
        </li>
      ))}
    </ul>
  );
}

export default SkillsPanel;
