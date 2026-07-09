import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { StatCard } from "./StatCard";

const meta: Meta<typeof StatCard> = {
  title: "Plans/StatCard",
  component: StatCard,
};
export default meta;

type Story = StoryObj<typeof StatCard>;

export const Default: Story = {
  args: { label: "Steps", value: 4 },
};

export const Row: Story = {
  render: () => (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(140px, 1fr))", gap: "0.75rem" }}>
      <StatCard label="Steps" value={4} />
      <StatCard label="Approved" value={1} />
      <StatCard label="Pending review" value={2} />
    </div>
  ),
};
