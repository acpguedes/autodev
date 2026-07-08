import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { SAMPLE_FLOW } from "@/lib/flow/sample";

import { FlowCanvas } from "./FlowCanvas";

const meta: Meta<typeof FlowCanvas> = {
  title: "Flow/FlowCanvas",
  component: FlowCanvas,
  args: {
    manifest: SAMPLE_FLOW,
    selectedNodeId: null,
    errorNodeIds: new Set<string>(),
    onSelectNode: () => {},
  },
};
export default meta;

type Story = StoryObj<typeof FlowCanvas>;

export const Default: Story = {};

export const WithSelection: Story = {
  args: { selectedNodeId: SAMPLE_FLOW.nodes[0]?.id ?? null },
};

export const WithErrors: Story = {
  args: {
    errorNodeIds: new Set(SAMPLE_FLOW.nodes.slice(0, 2).map((n) => n.id)),
  },
};
