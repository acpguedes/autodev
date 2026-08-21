"use client";

import * as React from "react";

import { FileTreeBrowser } from "@/components/repository/FileTreeBrowser";
import { FileViewer } from "@/components/repository/FileViewer";
import { useShellHeader } from "@/components/shell/ShellProvider";
import { useTranslations } from "@/lib/i18n";

/**
 * Project file browser screen (E43-S4): a file tree over the project root
 * and an in-app read-only viewer for whichever file is selected, so the
 * generated project can be inspected without leaving the browser.
 *
 * @returns The files page.
 */
export default function FilesPage() {
  const { t } = useTranslations();
  const [selectedPath, setSelectedPath] = React.useState<string | null>(null);

  useShellHeader({
    title: t("files.pageTitle"),
    subtitle: t("files.pageSubtitle"),
  });

  return (
    <div className="flex h-full gap-4 p-8">
      <aside className="w-72 shrink-0 overflow-y-auto rounded-md border">
        <FileTreeBrowser onSelectFile={setSelectedPath} selectedPath={selectedPath} />
      </aside>
      <section className="min-w-0 flex-1 overflow-hidden rounded-md border">
        <FileViewer path={selectedPath} />
      </section>
    </div>
  );
}
