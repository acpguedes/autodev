import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { AgentFormDialog } from "./AgentFormDialog";
import { installExtensionsFetchMock } from "./storybook-mocks";

const meta: Meta<typeof AgentFormDialog> = {
  title: "Extensions/AgentFormDialog",
  component: AgentFormDialog,
  args: {
    open: true,
    onOpenChange: () => {},
    onSaved: () => {},
  },
  // Wired to `GET`/`PUT /v2/extensions/agents/{agentId}`; the mock answers
  // both so the edit-mode prefill and the submit flow both exercise the
  // real request wiring without a live backend.
  decorators: [
    (Story) => {
      installExtensionsFetchMock();
      return <Story />;
    },
  ],
};
export default meta;

type Story = StoryObj<typeof AgentFormDialog>;

/** Create mode: the agent id field is editable and every field starts empty. */
export const Create: Story = {
  args: {
    agentId: null,
  },
};

/**
 * Edit mode: the dialog fetches `GET /v2/extensions/agents/reviewer` on open
 * and prefills the form (agent id becomes read-only, "Save changes" replaces
 * "Create agent").
 */
export const Edit: Story = {
  args: {
    agentId: "reviewer",
  },
};
