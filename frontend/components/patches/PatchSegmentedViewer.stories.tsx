import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { useState } from "react";

import { PatchSegmentedViewer, type PatchViewerMode } from "./PatchSegmentedViewer";

const SAMPLE_DIFF = [
  "--- a/backend/api/middleware/rate_limit.py",
  "+++ b/backend/api/middleware/rate_limit.py",
  "@@ -1,3 +1,4 @@",
  " import time",
  "+import logging",
  "-DEFAULT_LIMIT = 10",
  "+DEFAULT_LIMIT = 100",
  " ",
].join("\n");

const SAMPLE_CONTENT = "import time\nimport logging\nDEFAULT_LIMIT = 100\n";

function Interactive({ isDryRun, initialMode }: { isDryRun: boolean; initialMode: PatchViewerMode }) {
  const [mode, setMode] = useState<PatchViewerMode>(initialMode);
  const [editValue, setEditValue] = useState(SAMPLE_CONTENT);
  return (
    <div style={{ width: 520, height: 320 }}>
      <PatchSegmentedViewer
        path="backend/api/middleware/rate_limit.py"
        isDryRun={isDryRun}
        diff={SAMPLE_DIFF}
        mode={mode}
        onModeChange={setMode}
        editValue={editValue}
        onEditValueChange={setEditValue}
      />
    </div>
  );
}

const meta: Meta<typeof PatchSegmentedViewer> = {
  title: "Patches/PatchSegmentedViewer",
  component: PatchSegmentedViewer,
};
export default meta;

type Story = StoryObj<typeof PatchSegmentedViewer>;

export const DiffMode: Story = {
  render: () => <Interactive isDryRun initialMode="diff" />,
};

export const EditMode: Story = {
  render: () => <Interactive isDryRun initialMode="edit" />,
};

export const AppliedNoDryRunBadge: Story = {
  render: () => <Interactive isDryRun={false} initialMode="diff" />,
};
