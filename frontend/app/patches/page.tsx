"use client";

import { FormEvent, useState } from "react";

import ChatLayout from "../../components/ChatLayout";
import { generatePatch } from "../../lib/api_ext";

export default function PatchesPage() {
  const [path, setPath] = useState("example.py");
  const [original, setOriginal] = useState("");
  const [updated, setUpdated] = useState("");
  const [diff, setDiff] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      const result = await generatePatch(path, original, updated);
      setDiff(result.diff || "(no changes)");
    } catch {
      setError("Patches endpoint unavailable. Start the backend to generate diffs.");
      setDiff(null);
    }
  }

  return (
    <ChatLayout currentView="dashboard">
      <section className="hero-card">
        <div>
          <p className="eyebrow">Patches</p>
          <h1>Unified-diff generation</h1>
          <p className="subtitle">
            Generate an auditable unified diff between two versions of a file.
          </p>
        </div>
      </section>

      <section className="panel-card">
        <form className="config-form" onSubmit={handleGenerate}>
          <div className="config-form__grid">
            <label className="config-form__full-width">
              <span>Path</span>
              <input value={path} onChange={(event) => setPath(event.target.value)} />
            </label>
            <label className="config-form__full-width">
              <span>Original</span>
              <textarea value={original} onChange={(event) => setOriginal(event.target.value)} />
            </label>
            <label className="config-form__full-width">
              <span>Updated</span>
              <textarea value={updated} onChange={(event) => setUpdated(event.target.value)} />
            </label>
          </div>
          <div className="config-form__actions">
            <button type="submit">Generate diff</button>
          </div>
        </form>

        {diff ? (
          <pre className="code-block">{diff}</pre>
        ) : (
          <p className="empty-state">{error ?? "Generate a diff to preview it here."}</p>
        )}
      </section>
    </ChatLayout>
  );
}
