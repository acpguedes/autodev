import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { PatchDiffView } from "./PatchDiffView";

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

const meta: Meta<typeof PatchDiffView> = {
  title: "Patches/PatchDiffView",
  component: PatchDiffView,
};
export default meta;

type Story = StoryObj<typeof PatchDiffView>;

export const WithChanges: Story = {
  render: () => (
    <div style={{ width: 480 }}>
      <PatchDiffView diff={SAMPLE_DIFF} />
    </div>
  ),
};

export const Empty: Story = {
  render: () => (
    <div style={{ width: 480 }}>
      <PatchDiffView diff="" />
    </div>
  ),
};
