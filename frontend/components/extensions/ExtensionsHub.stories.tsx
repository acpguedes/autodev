import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { ExtensionsHub } from "./ExtensionsHub";
import { installExtensionsFetchMock } from "./storybook-mocks";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const meta: Meta<typeof ExtensionsHub> = {
  title: "Extensions/ExtensionsHub",
  component: ExtensionsHub,
  parameters: { layout: "padded" },
};
export default meta;

type Story = StoryObj<typeof ExtensionsHub>;

/**
 * The loaded hub: four tabs (Agents, Skills, Plugins, MCP), each labelled
 * with its live item count, showing the Agents tab's cards by default.
 */
export const Default: Story = {
  decorators: [
    (Story) => {
      installExtensionsFetchMock();
      return <Story />;
    },
  ],
};

/** An empty catalog: every tab shows its "nothing registered yet" state. */
export const Empty: Story = {
  decorators: [
    (Story) => {
      window.fetch = (async () =>
        jsonResponse({
          schemaVersion: "1.0",
          items: [],
          page: { limit: 500, offset: 0, total: 0 },
        })) as typeof window.fetch;
      return <Story />;
    },
  ],
};

/** The catalog request fails: an error banner renders above the empty tabs. */
export const LoadError: Story = {
  decorators: [
    (Story) => {
      window.fetch = (async () => jsonResponse({ detail: "unavailable" }, 503)) as typeof window.fetch;
      return <Story />;
    },
  ],
};
