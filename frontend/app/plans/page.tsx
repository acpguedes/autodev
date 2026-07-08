"use client";

import { FormEvent, useState } from "react";

import { getPlan, type PlanDocument } from "../../lib/api_ext";
import { useShellHeader } from "@/components/shell/ShellProvider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function PlansPage() {
  useShellHeader({
    title: "Plans",
    subtitle: "Editable plans with approval gates.",
  });

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
    <div className="flex flex-col gap-6 p-8">
      <header className="flex flex-col gap-2">
        <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">Plans</p>
        <h1 className="font-serif text-2xl font-semibold text-ds-fg">
          Editable plans with approval gates
        </h1>
        <p className="text-sm text-ds-fg-3">
          Look up a persisted plan by session id and review its approval status.
        </p>
      </header>

      <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
        <CardContent className="flex flex-col gap-4 pt-6">
          <form className="flex flex-col gap-3 sm:flex-row" onSubmit={handleLookup}>
            <Input
              value={sessionId}
              onChange={(event) => setSessionId(event.target.value)}
              placeholder="session id"
              aria-label="Session id"
            />
            <Button type="submit">Load plan</Button>
          </form>

          {plan ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-ds-fg-3">Status: {plan.status}</p>
              <ol className="flex list-decimal flex-col gap-2 pl-5 text-sm text-ds-fg-2">
                {plan.steps.map((step, index) => (
                  <li key={`${index}-${step}`}>{step}</li>
                ))}
              </ol>
            </div>
          ) : (
            <p className="text-sm text-ds-fg-3">{error ?? "Enter a session id to load its plan."}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
