import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { I18nProvider } from "@/lib/i18n";
import type { PendingDecisionV2 } from "@/lib/execution_v2";

import { ActionApprovalPanel } from "./ActionApprovalPanel";

function decision(overrides: Partial<PendingDecisionV2>): PendingDecisionV2 {
  return {
    decisionId: "dec-1",
    runId: "run-1",
    taskId: "coding-1",
    category: "fs-write",
    prompt: "Approve create_file for task 'Implement backend/api'?",
    status: "pending",
    createdAt: new Date().toISOString(),
    expiresAt: new Date(Date.now() + 3600_000).toISOString(),
    ...overrides,
  };
}

const meta: Meta<typeof ActionApprovalPanel> = {
  title: "Execution/ActionApprovalPanel",
  component: ActionApprovalPanel,
  decorators: [
    (Story) => (
      <I18nProvider>
        <div style={{ maxWidth: 480 }}>
          <Story />
        </div>
      </I18nProvider>
    ),
  ],
  args: {
    busy: false,
    onApproveOnce: () => {},
    onApproveAlways: () => {},
    onDeny: () => {},
  },
};
export default meta;

type Story = StoryObj<typeof ActionApprovalPanel>;

export const FsWrite: Story = {
  args: { decision: decision({}) },
};

export const Shell: Story = {
  args: {
    decision: decision({
      category: "shell",
      taskId: "validation-1",
      prompt: "Approve run_command for task 'Run pytest for backend modules'?",
    }),
  },
};

export const Busy: Story = {
  args: { decision: decision({}), busy: true },
};
