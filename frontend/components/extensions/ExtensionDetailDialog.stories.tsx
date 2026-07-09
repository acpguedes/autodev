import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { ExtensionDetailDialog } from "./ExtensionDetailDialog";
import { MOCK_EXTENSION_ITEMS } from "./storybook-mocks";

const meta: Meta<typeof ExtensionDetailDialog> = {
  title: "Extensions/ExtensionDetailDialog",
  component: ExtensionDetailDialog,
  args: {
    open: true,
    onOpenChange: () => {},
    onToggle: () => {},
  },
};
export default meta;

type Story = StoryObj<typeof ExtensionDetailDialog>;

/**
 * A skill's read-only manifest detail, with an "Disable" action since it is
 * currently active. Skills have no upsert endpoint, so this dialog is the
 * only way to inspect one from the hub.
 */
export const SkillEnabled: Story = {
  args: {
    kind: "skill",
    item: MOCK_EXTENSION_ITEMS[2],
  },
};

/** A disabled plugin's detail, with an "Enable" action. */
export const PluginDisabled: Story = {
  args: {
    kind: "plugin",
    item: MOCK_EXTENSION_ITEMS[3],
  },
};

/** An MCP exposure's detail, showing its raw manifest detail (transport). */
export const McpEnabled: Story = {
  args: {
    kind: "mcp",
    item: MOCK_EXTENSION_ITEMS[4],
  },
};

/** The enable/disable action is disabled while a mutation is in flight. */
export const Toggling: Story = {
  args: {
    kind: "skill",
    item: MOCK_EXTENSION_ITEMS[2],
    toggling: true,
  },
};
