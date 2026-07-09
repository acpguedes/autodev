import type { Metadata } from "next";

import { FlowEditor } from "@/components/flow/FlowEditor";
import { ShellHeaderPortal } from "@/components/shell/ShellProvider";

export const metadata: Metadata = {
  title: "Flow Editor — AutoDev Architect",
  description:
    "Visual editor for flow.yaml manifests: graph canvas, deterministic round-trip, and real-time validation.",
};

export default function FlowsPage() {
  return (
    <>
      <ShellHeaderPortal
        title="Flows"
        subtitle="Visual editor for flow.yaml manifests."
      />
      <section className="flex h-full flex-col gap-4 p-6">
        <header>
          <h2 className="font-serif text-lg font-semibold text-ds-fg">Visual flow editor</h2>
          <p className="text-sm text-ds-fg-2">
            Create and edit <code className="font-mono">flow.yaml</code> manifests visually —
            nodes, conditional edges, sub-flows, map/reduce, and human checkpoints — with
            lossless YAML round-trip and immediate graph validation.
          </p>
        </header>
        <div className="min-h-0 flex-1">
          <FlowEditor />
        </div>
      </section>
    </>
  );
}
