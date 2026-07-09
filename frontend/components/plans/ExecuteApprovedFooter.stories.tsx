import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { ExecuteApprovedFooter } from "./ExecuteApprovedFooter";

const meta: Meta<typeof ExecuteApprovedFooter> = {
  title: "Plans/ExecuteApprovedFooter",
  component: ExecuteApprovedFooter,
  args: {
    onExecute: () => {},
    label: "Execute approved plan",
    executingLabel: "Executing...",
    needsApprovalLabel: "Approve at least one step to execute",
  },
};
export default meta;

type Story = StoryObj<typeof ExecuteApprovedFooter>;

export const Disabled: Story = {
  args: { approvedCount: 0, executing: false },
};

export const Enabled: Story = {
  args: { approvedCount: 2, executing: false },
};

export const Executing: Story = {
  args: { approvedCount: 2, executing: true },
};
