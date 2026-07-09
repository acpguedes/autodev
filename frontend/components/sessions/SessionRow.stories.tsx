import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { SessionRow } from "./SessionRow";

const meta: Meta<typeof SessionRow> = {
  title: "Sessions/SessionRow",
  component: SessionRow,
  parameters: { nextjs: { appDirectory: true } },
  decorators: [
    (Story) => (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Goal</TableHead>
            <TableHead>Session id</TableHead>
            <TableHead>Runs</TableHead>
            <TableHead>Last run</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Reopen</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <Story />
        </TableBody>
      </Table>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof SessionRow>;

export const Running: Story = {
  args: {
    sessionId: "session-a1b2c3",
    goal: "Bootstrap AutoDev project scaffolding",
    status: "running",
    runCount: 3,
    lastRunAt: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  },
};

export const Done: Story = {
  args: {
    sessionId: "session-d4e5f6",
    goal: "Add pgvector-backed repository search",
    status: "completed",
    runCount: 7,
    lastRunAt: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
  },
};

export const Failed: Story = {
  args: {
    sessionId: "session-g7h8i9",
    goal: "Wire provider config to the control plane",
    status: "failed",
    runCount: 1,
    lastRunAt: new Date(Date.now() - 26 * 60 * 60 * 1000).toISOString(),
  },
};

export const NoRunsYet: Story = {
  args: {
    sessionId: "session-j1k2l3",
    goal: "",
    status: "pending",
    runCount: 0,
    lastRunAt: null,
  },
};

export const Loading: Story = {
  args: {
    sessionId: "session-m4n5o6",
    goal: "Draft the extensions hub screen",
    status: "pending",
    runCount: null,
    lastRunAt: null,
  },
};
