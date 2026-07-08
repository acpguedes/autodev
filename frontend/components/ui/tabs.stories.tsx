import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Tabs, TabsList, TabsTrigger, TabsContent } from "./tabs";

const meta: Meta<typeof Tabs> = {
  title: "UI/Tabs",
  component: Tabs,
};
export default meta;

type Story = StoryObj<typeof Tabs>;

export const Default: Story = {
  render: () => (
    <Tabs defaultValue="plan" style={{ width: 320 }}>
      <TabsList>
        <TabsTrigger value="plan">Plan</TabsTrigger>
        <TabsTrigger value="diff">Diff</TabsTrigger>
        <TabsTrigger value="logs">Logs</TabsTrigger>
      </TabsList>
      <TabsContent value="plan">Plan steps and approval gates.</TabsContent>
      <TabsContent value="diff">Unified diff preview.</TabsContent>
      <TabsContent value="logs">Execution logs.</TabsContent>
    </Tabs>
  ),
};
