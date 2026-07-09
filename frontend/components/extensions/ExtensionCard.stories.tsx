import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { ExtensionCard } from "./ExtensionCard";
import { MOCK_EXTENSION_ITEMS } from "./storybook-mocks";

const meta: Meta<typeof ExtensionCard> = {
  title: "Extensions/ExtensionCard",
  component: ExtensionCard,
  args: {
    onOpen: () => {},
    onToggle: () => {},
  },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 360 }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof ExtensionCard>;

/** An enabled agent card, showing its version and capability description. */
export const AgentEnabled: Story = {
  args: {
    kind: "agent",
    item: MOCK_EXTENSION_ITEMS[0],
  },
};

/** A disabled agent card — the status pill and toggle both read "off". */
export const AgentDisabled: Story = {
  args: {
    kind: "agent",
    item: MOCK_EXTENSION_ITEMS[1],
  },
};

/** A skill card, exposed via a plugin, showing its trigger description. */
export const SkillEnabled: Story = {
  args: {
    kind: "skill",
    item: MOCK_EXTENSION_ITEMS[2],
  },
};

/** A disabled plugin card, showing its extension points. */
export const PluginDisabled: Story = {
  args: {
    kind: "plugin",
    item: MOCK_EXTENSION_ITEMS[3],
  },
};

/** An MCP exposure card, standalone (no owning plugin). */
export const McpEnabled: Story = {
  args: {
    kind: "mcp",
    item: MOCK_EXTENSION_ITEMS[4],
  },
};

/** The toggle is disabled and shows a busy state while a mutation is in flight. */
export const Toggling: Story = {
  args: {
    kind: "agent",
    item: MOCK_EXTENSION_ITEMS[0],
    toggling: true,
  },
};
