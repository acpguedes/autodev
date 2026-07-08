"use client";

import { FormEvent, useState } from "react";

import ChatLayout from "../../components/ChatLayout";
import { getPlan, type PlanDocument } from "../../lib/api_ext";

export default function PlansPage() {
  const [sessionId, setSessionId] = useState("");
  const [plan, setPlan] = useState<PlanDocument | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      setPlan(await getPlan(sessionId));
    } catch {
      setError("No plan found for that session (or the plans endpoint is unavailable).");
      setPlan(null);
    }
  }

  return (
    <ChatLayout currentView="plans">
      <section className="hero-card">
        <div>
          <p className="eyebrow">Plans</p>
          <h1>Editable plans with approval gates</h1>
          <p className="subtitle">
            Look up a persisted plan by session id and review its approval status.
          </p>
        </div>
      </section>

      <section className="panel-card">
        <form className="search-form" onSubmit={handleLookup}>
          <input
            value={sessionId}
            onChange={(event) => setSessionId(event.target.value)}
            placeholder="session id"
          />
          <button type="submit">Load plan</button>
        </form>

        {plan ? (
          <div className="repository-context">
            <p className="run-card__meta">Status: {plan.status}</p>
            <ol className="note-list">
              {plan.steps.map((step, index) => (
                <li key={`${index}-${step}`}>{step}</li>
              ))}
            </ol>
          </div>
        ) : (
          <p className="empty-state">{error ?? "Enter a session id to load its plan."}</p>
        )}
      </section>
    </ChatLayout>
  );
}
