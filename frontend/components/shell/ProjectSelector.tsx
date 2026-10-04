"use client";

import type { Route } from "next";
import Link from "next/link";
import * as React from "react";
import useSWR from "swr";

import { activateProjectV2, listProjectsV2 } from "@/lib/projects_v2";
import { useTranslations } from "@/lib/i18n";

/**
 * Project selector for the contextual header (E62-S4-T3): switches the active
 * project, or links to the onboarding view when no project exists yet.
 *
 * @returns The selector, or a link to onboarding.
 */
export function ProjectSelector(): React.JSX.Element | null {
  const { t } = useTranslations();
  const projects = useSWR("shell:projects", listProjectsV2, { shouldRetryOnError: false });

  if (projects.error || !projects.data) {
    return null;
  }
  const { items, activeProjectId } = projects.data;
  if (items.length === 0 || activeProjectId === null) {
    return (
      <Link
        href={"/projects" as Route}
        className="rounded-ds-md border border-ds-line bg-ds-bg-2 px-2.5 py-1.5 text-[12px] text-ds-fg-2"
      >
        {t("projects.selector.choose")}
      </Link>
    );
  }
  return (
    <label className="hidden items-center gap-2 text-[12px] text-ds-fg-2 sm:flex">
      <span className="sr-only">{t("projects.selector.label")}</span>
      <select
        aria-label={t("projects.selector.label")}
        className="max-w-[14rem] truncate rounded-ds-md border border-ds-line bg-ds-bg-2 px-2.5 py-1.5"
        value={activeProjectId}
        onChange={async (event) => {
          await activateProjectV2(event.target.value);
          await projects.mutate();
        }}
      >
        {items.map((project) => (
          <option key={project.projectId} value={project.projectId}>
            {project.name}
          </option>
        ))}
      </select>
    </label>
  );
}

export default ProjectSelector;
