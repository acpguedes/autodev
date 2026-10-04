"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  createProjectV2,
  initProjectV2,
  openProjectV2,
  type ProjectV2,
} from "@/lib/projects_v2";
import { useTranslations } from "@/lib/i18n";

type Path = "open" | "init" | "create";

/**
 * Onboarding for when no project is active (E62-S4-T3): the absence of
 * `.autodev/` presents a choice between three explicit paths rather than
 * assuming one. Initializing an existing directory never restructures it.
 *
 * @param props.onDone - Called with the project once a path succeeds.
 * @returns The onboarding form.
 */
export function ProjectOnboarding({
  onDone,
}: {
  onDone: (project: ProjectV2) => void;
}): React.JSX.Element {
  const { t } = useTranslations();
  const [root, setRoot] = React.useState("");
  const [busy, setBusy] = React.useState<Path | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const run = async (path: Path): Promise<void> => {
    setBusy(path);
    setError(null);
    try {
      const action = { open: openProjectV2, init: initProjectV2, create: createProjectV2 }[path];
      onDone(await action(root.trim()));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="flex max-w-xl flex-col gap-4">
      <p className="text-[13px] text-ds-fg-2">{t("projects.onboarding.intro")}</p>
      <label className="flex flex-col gap-1.5">
        <span className="text-[12px] text-ds-fg-2">{t("projects.onboarding.rootLabel")}</span>
        <Input value={root} onChange={(event) => setRoot(event.target.value)} />
      </label>
      <div className="flex flex-wrap gap-2">
        {(["open", "init", "create"] as const).map((path) => (
          <Button
            key={path}
            type="button"
            variant={path === "open" ? "default" : "outline"}
            disabled={!root.trim() || busy !== null}
            onClick={() => void run(path)}
          >
            {t(`projects.onboarding.${path}`)}
          </Button>
        ))}
      </div>
      <p className="text-[12px] text-ds-fg-3">{t("projects.onboarding.initNote")}</p>
      {error ? (
        <p role="alert" className="text-[12px] text-red-600">
          {error}
        </p>
      ) : null}
    </section>
  );
}

export default ProjectOnboarding;
