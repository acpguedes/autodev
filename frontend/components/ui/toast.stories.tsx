import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Toast } from "./toast";

const meta: Meta<typeof Toast> = {
  title: "UI/Toast",
  component: Toast,
  args: {
    title: "Patch applied",
    description: "3 files changed, validation passed.",
  },
};
export default meta;

type Story = StoryObj<typeof Toast>;

export const Default: Story = {
  render: (args) => (
    <div style={{ maxWidth: 360 }}>
      <Toast {...args} />
    </div>
  ),
};

export const Destructive: Story = {
  args: {
    variant: "destructive",
    title: "Validation failed",
    description: "2 tests failed after applying the patch.",
  },
  render: (args) => (
    <div style={{ maxWidth: 360 }}>
      <Toast {...args} />
    </div>
  ),
};
