import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { I18nProvider } from "@/lib/i18n";

import { DynamicPermissionsList } from "./DynamicPermissionsList";

const meta: Meta<typeof DynamicPermissionsList> = {
  title: "Execution/DynamicPermissionsList",
  component: DynamicPermissionsList,
  decorators: [
    (Story) => (
      <I18nProvider>
        <div style={{ maxWidth: 480 }}>
          <Story />
        </div>
      </I18nProvider>
    ),
  ],
  args: {
    busyIds: new Set<string>(),
    onRevoke: () => {},
  },
};
export default meta;

type Story = StoryObj<typeof DynamicPermissionsList>;

export const Empty: Story = {
  args: { permissions: [] },
};

export const WithGrants: Story = {
  args: {
    permissions: [
      { permissionId: "perm-1", category: "shell", scopeKind: "project", scopeId: "*", pattern: "pytest" },
      { permissionId: "perm-2", category: "validation", scopeKind: "project", scopeId: "*", pattern: "ruff" },
    ],
  },
};

export const RevokeInFlight: Story = {
  args: {
    permissions: [
      { permissionId: "perm-1", category: "shell", scopeKind: "project", scopeId: "*", pattern: "pytest" },
    ],
    busyIds: new Set(["perm-1"]),
  },
};
