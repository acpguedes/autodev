import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "./select";

const meta: Meta<typeof Select> = {
  title: "UI/Select",
  component: Select,
};
export default meta;

type Story = StoryObj<typeof Select>;

export const Default: Story = {
  render: () => (
    <Select defaultValue="researcher">
      <SelectTrigger style={{ width: 220 }} aria-label="Agent role">
        <SelectValue placeholder="Select an agent" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="researcher">Researcher</SelectItem>
        <SelectItem value="coder">Coder</SelectItem>
        <SelectItem value="tester">Tester</SelectItem>
        <SelectItem value="reviewer">Reviewer</SelectItem>
      </SelectContent>
    </Select>
  ),
};
