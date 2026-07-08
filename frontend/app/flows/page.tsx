import type { Metadata } from "next";

import ChatLayout from "@/components/ChatLayout";
import { FlowEditor } from "@/components/flow/FlowEditor";

export const metadata: Metadata = {
  title: "Flow Editor — AutoDev Architect",
  description:
    "Visual editor for flow.yaml manifests: graph canvas, deterministic round-trip, and real-time validation.",
};

export default function FlowsPage() {
  return (
    <ChatLayout currentView="flows">
      <section className="flex h-full flex-col gap-4 p-6">
        <header>
          <h2 className="text-lg font-semibold text-foreground">Visual flow editor</h2>
          <p className="text-sm text-muted-foreground">
            Create and edit <code className="font-mono">flow.yaml</code> manifests visually —
            nodes, conditional edges, sub-flows, map/reduce, and human checkpoints — with
            lossless YAML round-trip and immediate graph validation.
          </p>
        </header>
        <div className="min-h-0 flex-1">
          <FlowEditor />
        </div>
      </section>
    </ChatLayout>
  );
}
