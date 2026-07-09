import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { useState } from "react";

import type { ChangedFileV2 } from "@/lib/api_patches_v2";

import { PatchFileList } from "./PatchFileList";

const SAMPLE_FILES: ChangedFileV2[] = [
  {
    schemaVersion: "1.0",
    patch_id: "patch-1",
    path: "backend/api/middleware/rate_limit.py",
    status: "proposed",
    added_lines: 12,
    removed_lines: 3,
  },
  {
    schemaVersion: "1.0",
    patch_id: "patch-2",
    path: "frontend/lib/diff.ts",
    status: "applied",
    added_lines: 40,
    removed_lines: 0,
  },
  {
    schemaVersion: "1.0",
    patch_id: "patch-3",
    path: "README.md",
    status: "discarded",
    added_lines: 2,
    removed_lines: 2,
  },
];

const meta: Meta<typeof PatchFileList> = {
  title: "Patches/PatchFileList",
  component: PatchFileList,
};
export default meta;

type Story = StoryObj<typeof PatchFileList>;

export const Empty: Story = {
  render: () => (
    <div style={{ width: 300 }}>
      <PatchFileList files={[]} selectedPatchId={null} onSelect={() => {}} />
    </div>
  ),
};

export const Populated: Story = {
  render: () => (
    <div style={{ width: 300 }}>
      <PatchFileList files={SAMPLE_FILES} selectedPatchId={null} onSelect={() => {}} />
    </div>
  ),
};

export const WithSelection: Story = {
  render: () => {
    function Interactive() {
      const [selected, setSelected] = useState<string | null>("patch-2");
      return (
        <div style={{ width: 300 }}>
          <PatchFileList files={SAMPLE_FILES} selectedPatchId={selected} onSelect={setSelected} />
        </div>
      );
    }
    return <Interactive />;
  },
};
