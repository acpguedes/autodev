import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import {
  createPanelRegistry,
  type PanelComponent,
  type PanelRegistry,
} from "@/lib/panels/registry";

import {
  ExampleRunSummaryPanel,
  exampleRunSummaryManifest,
} from "./ExampleRunSummaryPanel";
import { PanelManager } from "./PanelManager";
import { PanelSlotOutlet } from "./PanelSlotOutlet";

const withExamplePanel = (): PanelRegistry => {
  const registry = createPanelRegistry({ storage: null });
  registry.register({
    manifest: exampleRunSummaryManifest,
    Component: ExampleRunSummaryPanel,
    source: "builtin",
  });
  return registry;
};

const meta: Meta<typeof PanelSlotOutlet> = {
  title: "Panels/PluggablePanels",
  component: PanelSlotOutlet,
};
export default meta;

type Story = StoryObj<typeof PanelSlotOutlet>;

export const ExamplePanelInSlot: Story = {
  render: () => (
    <div style={{ width: 360 }}>
      <PanelSlotOutlet slot="run.detail.sidebar" registry={withExamplePanel()} />
    </div>
  ),
};

const FaultyPanel: PanelComponent = () => {
  throw new Error("intentional panel crash (storybook)");
};

export const FaultyPanelIsIsolated: Story = {
  render: () => {
    const registry = withExamplePanel();
    registry.register({
      manifest: {
        id: "storybook/faulty.panel",
        title: "Faulty panel",
        slot: "run.detail.sidebar",
        contract: "^1.0",
        description: "Throws on render; the boundary must isolate it.",
      },
      Component: FaultyPanel,
      source: "storybook",
    });
    return (
      <div style={{ width: 360 }}>
        <PanelSlotOutlet slot="run.detail.sidebar" registry={registry} />
      </div>
    );
  },
};

export const Manager: Story = {
  render: () => (
    <div style={{ width: 480 }}>
      <PanelManager registry={withExamplePanel()} />
    </div>
  ),
};
