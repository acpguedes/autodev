import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  TableCaption,
} from "./table";

const meta: Meta<typeof Table> = {
  title: "UI/Table",
  component: Table,
};
export default meta;

type Story = StoryObj<typeof Table>;

export const Default: Story = {
  render: () => (
    <Table>
      <TableCaption>Recent agent runs.</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Agent</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Duration</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow>
          <TableCell>researcher</TableCell>
          <TableCell>Completed</TableCell>
          <TableCell>42s</TableCell>
        </TableRow>
        <TableRow>
          <TableCell>coder</TableCell>
          <TableCell>Running</TableCell>
          <TableCell>1m 12s</TableCell>
        </TableRow>
      </TableBody>
    </Table>
  ),
};
