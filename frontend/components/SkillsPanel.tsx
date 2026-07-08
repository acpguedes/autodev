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
    return <p className="text-sm text-ds-fg-3">{error}</p>;
  }

  if (skills.length === 0) {
    return <p className="text-sm text-ds-fg-3">Loading skills...</p>;
  }

  return (
    <ul className="flex flex-col gap-2 text-sm text-ds-fg-2">
      {skills.map((skill) => (
        <li key={skill.name}>
          <strong className="font-semibold text-ds-fg">{skill.name}</strong> — {skill.description}
        </li>
      ))}
    </ul>
  );
}

export default SkillsPanel;
