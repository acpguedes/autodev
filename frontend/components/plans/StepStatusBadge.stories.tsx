import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { StepStatusBadge } from "./StepStatusBadge";

const meta: Meta<typeof StepStatusBadge> = {
  title: "Plans/StepStatusBadge",
  component: StepStatusBadge,
};
export default meta;

type Story = StoryObj<typeof StepStatusBadge>;

export const Default: Story = {
  args: { state: "under_review", label: "Awaiting review" },
};

export const AllStates: Story = {
  render: () => (
    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
      <StepStatusBadge state="draft" label="Draft" />
      <StepStatusBadge state="under_review" label="Awaiting review" />
      <StepStatusBadge state="approved" label="Approved" />
      <StepStatusBadge state="rejected" label="Rejected" />
      <StepStatusBadge state="executing" label="Executing" />
      <StepStatusBadge state="completed" label="Completed" />
    </div>
  ),
};
