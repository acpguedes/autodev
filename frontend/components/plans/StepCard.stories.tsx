import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { I18nProvider } from "@/lib/i18n";
import type { PlanStepV2 } from "@/lib/plans_v2";

import { StepCard } from "./StepCard";

function step(overrides: Partial<PlanStepV2>): PlanStepV2 {
  return {
    schemaVersion: "2.0",
    session_id: "demo-session",
    step_index: 0,
    content: "Add rate limiting\n\nIntroduce a token-bucket limiter on the public API.",
    state: "under_review",
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

const meta: Meta<typeof StepCard> = {
  title: "Plans/StepCard",
  component: StepCard,
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
    index: 1,
    busy: false,
    onSave: async () => true,
    onApprove: () => {},
    onReject: () => {},
    onRemove: () => {},
  },
};
export default meta;

type Story = StoryObj<typeof StepCard>;

export const UnderReview: Story = {
  args: { step: step({ state: "under_review" }) },
};

export const Approved: Story = {
  args: { index: 2, step: step({ step_index: 1, state: "approved" }) },
};

export const Rejected: Story = {
  args: { index: 3, step: step({ step_index: 2, state: "rejected" }) },
};

export const Executing: Story = {
  args: { index: 4, step: step({ step_index: 3, state: "executing" }) },
};

export const Completed: Story = {
  args: { index: 5, step: step({ step_index: 4, state: "completed" }) },
};

export const Busy: Story = {
  args: { step: step({ state: "under_review" }), busy: true },
};
