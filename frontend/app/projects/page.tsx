"use client";

import * as React from "react";
import useSWR from "swr";

import { ProjectOnboarding } from "@/components/projects/ProjectOnboarding";
import { useShellHeader } from "@/components/shell/ShellProvider";
import { useTranslations } from "@/lib/i18n";
import { listProjectsV2 } from "@/lib/projects_v2";

/**
 * Projects screen (E62-S4-T3): lists the tenant's projects and, as the
 * onboarding view, offers open / initialize / create.
 *
 * @returns The projects page.
 */
export default function ProjectsPage() {
  const { t } = useTranslations();
  const projects = useSWR("shell:projects", listProjectsV2, { shouldRetryOnError: false });

  useShellHeader({ title: t("projects.pageTitle"), subtitle: t("projects.pageSubtitle") });

  return (
    <div className="flex flex-col gap-8 p-8">
      {projects.data && projects.data.items.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {projects.data.items.map((project) => (
            <li key={project.projectId} className="text-[13px] text-ds-fg">
              <span className="font-semibold">{project.name}</span>
              {project.active ? <span className="ml-2 text-ds-fg-3">({t("projects.active")})</span> : null}
              <span className="ml-2 text-ds-fg-3">{project.rootPath}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <ProjectOnboarding onDone={() => void projects.mutate()} />
    </div>
  );
}
