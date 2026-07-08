import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Skeleton } from "./skeleton";

const meta: Meta<typeof Skeleton> = {
  title: "UI/Skeleton",
  component: Skeleton,
};
export default meta;

type Story = StoryObj<typeof Skeleton>;

export const Default: Story = {
  render: () => (
    <div style={{ display: "grid", gap: "0.5rem", width: 240 }}>
      <Skeleton style={{ height: "1rem", width: "100%" }} />
      <Skeleton style={{ height: "1rem", width: "80%" }} />
      <Skeleton style={{ height: "1rem", width: "60%" }} />
    </div>
  ),
};
