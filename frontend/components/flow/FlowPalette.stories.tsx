import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import type { FlowCatalogItemV2 } from "@/lib/api_v2";

import { FlowPalette } from "./FlowPalette";

const SAMPLE_CATALOG: FlowCatalogItemV2[] = [
  {
    id: "autodev/flow-feature-delivery",
    version: "1.0.0",
    name: "Feature delivery",
    description: "Plan, implement, validate, and request human approval.",
    hostApi: "v2",
    triggers: [],
  },
  {
    id: "autodev/flow-incident-triage",
    version: "2.1.0",
    name: "Incident triage",
    description: "Analyze, gather context, and route for review.",
    hostApi: "v2",
    triggers: [],
  },
];

const meta: Meta<typeof FlowPalette> = {
  title: "Flow/FlowPalette",
  component: FlowPalette,
  args: {
    catalog: SAMPLE_CATALOG,
    catalogLoading: false,
    catalogError: null,
    selectedNodeId: null,
    onInsertAgent: () => {},
    onInsertControl: () => {},
    onNewFlow: () => {},
  },
  decorators: [
    (Story) => (
      <div style={{ height: 640, width: 280 }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof FlowPalette>;

/** Default state: flows library populated, no node selected (standalone inserts). */
export const Default: Story = {};

/** A node is selected on the canvas — Agents/Flow-control hint switches to "Connects from". */
export const WithSelectedNode: Story = {
  args: { selectedNodeId: "plan-feature" },
};

/** Flows library still loading the /v2/flows catalog. */
export const CatalogLoading: Story = {
  args: { catalog: [], catalogLoading: true },
};

/** Flows library failed to load (backend unavailable). */
export const CatalogError: Story = {
  args: { catalog: [], catalogLoading: false, catalogError: "Flows endpoint unavailable." },
};

/** No flows registered yet — only "New blank flow" is actionable. */
export const CatalogEmpty: Story = {
  args: { catalog: [], catalogLoading: false, catalogError: null },
};
