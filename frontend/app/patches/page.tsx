"use client";

import { FormEvent, useState } from "react";

import { generatePatch } from "../../lib/api_ext";
import { useShellHeader } from "@/components/shell/ShellProvider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function PatchesPage() {
  useShellHeader({
    title: "Patches",
    subtitle: "Auditable unified-diff generation.",
  });

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

  const fieldLabel = "text-sm font-medium text-ds-fg-2";
  const textareaClass =
    "min-h-[110px] w-full resize-y rounded-ds-md border border-ds-line bg-ds-bg-2 px-3 py-2 text-sm text-ds-fg shadow-sm transition-colors placeholder:text-ds-fg-3 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ds-accent";

  return (
    <div className="flex flex-col gap-6 p-8">
      <header className="flex flex-col gap-2">
        <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">Patches</p>
        <h1 className="font-serif text-2xl font-semibold text-ds-fg">Unified-diff generation</h1>
        <p className="text-sm text-ds-fg-3">
          Generate an auditable unified diff between two versions of a file.
        </p>
      </header>

      <Card className="border-ds-line bg-ds-bg-2 shadow-ds-sm">
        <CardContent className="flex flex-col gap-4 pt-6">
          <form className="flex flex-col gap-4" onSubmit={handleGenerate}>
            <label className="flex flex-col gap-1.5">
              <span className={fieldLabel}>Path</span>
              <Input value={path} onChange={(event) => setPath(event.target.value)} />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className={fieldLabel}>Original</span>
              <textarea
                className={textareaClass}
                value={original}
                onChange={(event) => setOriginal(event.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className={fieldLabel}>Updated</span>
              <textarea
                className={textareaClass}
                value={updated}
                onChange={(event) => setUpdated(event.target.value)}
              />
            </label>
            <div className="flex justify-end">
              <Button type="submit">Generate diff</Button>
            </div>
          </form>

          {diff ? (
            <pre className="overflow-x-auto whitespace-pre-wrap rounded-ds-md border border-ds-line bg-ds-bg-3 p-4 font-mono text-[13px] text-ds-fg-2">
              {diff}
            </pre>
          ) : (
            <p className="text-sm text-ds-fg-3">{error ?? "Generate a diff to preview it here."}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
