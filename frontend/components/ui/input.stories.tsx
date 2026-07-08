import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Input } from "./input";

const meta: Meta<typeof Input> = {
  title: "UI/Input",
  component: Input,
  args: { placeholder: "Type here..." },
};
export default meta;

type Story = StoryObj<typeof Input>;

export const Default: Story = {
  render: (args) => (
    <label style={{ display: "grid", gap: "0.35rem", maxWidth: 320 }}>
      <span>Session ID</span>
      <Input {...args} />
    </label>
  ),
};

export const Disabled: Story = {
  args: { disabled: true, value: "read only" },
};
