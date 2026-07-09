import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { StatusGlowDot } from "./StatusGlowDot";

const meta: Meta<typeof StatusGlowDot> = {
  title: "Sessions/StatusGlowDot",
  component: StatusGlowDot,
};
export default meta;

type Story = StoryObj<typeof StatusGlowDot>;

export const Running: Story = {
  args: { tone: "warn", label: "Running" },
};

export const Done: Story = {
  args: { tone: "success", label: "Done" },
};

export const Failed: Story = {
  args: { tone: "danger", label: "Failed" },
};

export const AllTones: Story = {
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      <StatusGlowDot tone="success" label="Done" />
      <StatusGlowDot tone="warn" label="Running" />
      <StatusGlowDot tone="danger" label="Failed" />
      <StatusGlowDot tone="neutral" label="Unknown" />
    </div>
  ),
};
