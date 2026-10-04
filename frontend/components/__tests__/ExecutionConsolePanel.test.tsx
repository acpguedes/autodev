import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ExecutionActionEvent } from "@/lib/execution_events";
import type { RunResponse } from "@/lib/api";

const hook = vi.hoisted(() => ({
  value: { events: [] as unknown[], streamStatus: "open" as string },
}));

vi.mock("@/lib/execution_events", () => ({
  useExecutionActionLog: () => hook.value,
}));

import { I18nProvider } from "@/lib/i18n/I18nProvider";

import { ExecutionConsolePanel } from "../ExecutionConsolePanel";

function ev(partial: Partial<ExecutionActionEvent> & Pick<ExecutionActionEvent, "type" | "actionId">): ExecutionActionEvent {
  return { taskId: "t1", frameId: null, receivedAt: "", ...partial };
}

function run(runId: string, results: Array<Record<string, unknown>>): RunResponse {
  return { run_id: runId, run_type: "agent", status: "completed", results } as unknown as RunResponse;
}

function panel(runs: RunResponse[]) {
  return (
    <I18nProvider>
      <ExecutionConsolePanel runs={runs} isBusy={false} activeRunId="r1" />
    </I18nProvider>
  );
}

function renderPanel(runs: RunResponse[], events: ExecutionActionEvent[], streamStatus = "open") {
  hook.value = { events, streamStatus };
  return render(panel(runs));
}

describe("ExecutionConsolePanel", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders no entry for a zero-action result", () => {
    renderPanel(
      [run("r2", [{ agent: "planner", content: "LLM prose", metadata: { description: "model text", actions: [] } }])],
      []
    );
    expect(screen.queryByText("model text")).toBeNull();
    expect(screen.queryByText("LLM prose")).toBeNull();
    expect(screen.getByText(/only real operations/)).toBeTruthy();
  });

  it("collapses started+completed into one entry with state and exit code", () => {
    renderPanel([], [
      ev({ type: "execution.action.started", actionId: "a1", frameId: "1", command: ["pytest", "-q"] }),
      ev({ type: "execution.action.completed", actionId: "a1", frameId: "2", status: "succeeded", exitCode: 0, stdout: "1 passed" }),
    ]);
    expect(screen.getAllByText("$ pytest -q")).toHaveLength(1);
    expect(screen.getByText("completed")).toBeTruthy();
    expect(screen.getByText(/exit code: 0/)).toBeTruthy();
    expect(screen.getByText("1 passed")).toBeTruthy();
  });

  it("renders an actionId present in both the stream and polled runs once, for the active run", () => {
    const polled = run("r1", [
      { agent: "coder", metadata: { actions: [{ action_id: "a1", status: "succeeded", command: ["ls"], stdout: "x" }] } },
    ]);
    renderPanel([polled], [ev({ type: "execution.action.started", actionId: "a1", frameId: "1", command: ["ls"] })]);
    expect(screen.getAllByText("$ ls")).toHaveLength(1);
  });

  it("falls back to polled history for the active run when the stream errors", () => {
    const polled = run("r1", [
      { agent: "coder", metadata: { actions: [{ action_id: "a9", status: "succeeded", command: ["ls"], stdout: "polled-out" }] } },
    ]);
    renderPanel([polled], [], "error");
    expect(screen.getByText("polled-out")).toBeTruthy();
  });

  it("hides the active run's polled entries while the stream is healthy", () => {
    const polled = run("r1", [
      { agent: "coder", metadata: { actions: [{ action_id: "a9", status: "succeeded", command: ["ls"], stdout: "polled-out" }] } },
    ]);
    renderPanel([polled], []);
    expect(screen.queryByText("polled-out")).toBeNull();
  });

  it("appends output chunks by seq, then the completed output replaces them", () => {
    const base = [
      ev({ type: "execution.action.started", actionId: "a1", frameId: "1", command: ["make"] }),
      ev({ type: "execution.action.output", actionId: "a1", frameId: "3", stream: "stdout", chunk: "B\n", seq: 1 }),
      ev({ type: "execution.action.output", actionId: "a1", frameId: "2", stream: "stdout", chunk: "A\n", seq: 0 }),
    ];
    const { container, rerender } = renderPanel([], base);
    expect(container.querySelector("pre")?.textContent).toBe("A\nB\n");
    expect(screen.getByText("running")).toBeTruthy();

    hook.value = {
      events: [...base, ev({ type: "execution.action.completed", actionId: "a1", frameId: "4", status: "succeeded", exitCode: 0, stdout: "FULL" })],
      streamStatus: "open",
    };
    rerender(panel([]));
    expect(container.querySelector("pre")?.textContent).toBe("FULL");
  });

  it("orders entries by frame id and renders agent, cancelled state and truncation notice", () => {
    renderPanel([], [
      ev({ type: "execution.action.started", actionId: "b", frameId: "10", command: ["second"] }),
      ev({ type: "execution.action.started", actionId: "a", frameId: "9", command: ["first"] }),
      ev({ type: "execution.action.failed", actionId: "a", frameId: "11", status: "cancelled", sourceAgent: "coder", truncated: true, stderr: "tail" }),
    ]);
    const codes = screen.getAllByText(/^\$ (first|second)$/).map((node) => node.textContent);
    expect(codes).toEqual(["$ first", "$ second"]);
    expect(screen.getByText("cancelled")).toBeTruthy();
    expect(screen.getByText(/agent: coder/)).toBeTruthy();
    expect(screen.getByText(/Output truncated/)).toBeTruthy();
  });

  it("renders a pre-E64 event without sourceAgent, truncated or exit code", () => {
    renderPanel([], [
      ev({ type: "execution.action.started", actionId: "a1", frameId: "1", path: "main.py" }),
      ev({ type: "execution.action.completed", actionId: "a1", frameId: "2", status: "succeeded" }),
    ]);
    expect(screen.getByText("$ write main.py")).toBeTruthy();
    expect(screen.queryByText(/agent:/)).toBeNull();
    expect(screen.queryByText(/Output truncated/)).toBeNull();
  });
});
