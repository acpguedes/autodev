import { describe, expect, it } from "vitest";

import {
  formatActionCommand,
  formatStepLabel,
  transcriptLineFromActionEvent,
  transcriptLineFromActionResult,
} from "../transcript";

describe("formatStepLabel", () => {
  it("uses the plain-language title when present", () => {
    expect(formatStepLabel("Creating main.py", "coding-file-1")).toBe("Creating main.py");
  });

  it("falls back to the raw id when the task has no title", () => {
    expect(formatStepLabel(undefined, "coding-file-1")).toBe("coding-file-1");
    expect(formatStepLabel("", "coding-file-1")).toBe("coding-file-1");
  });
});

describe("formatActionCommand", () => {
  it("renders the real command when present", () => {
    expect(formatActionCommand({ actionId: "a1", taskId: "t1", command: ["pytest", "-q"] })).toBe(
      "$ pytest -q"
    );
  });

  it("renders a write line for a file target when there is no command", () => {
    expect(formatActionCommand({ actionId: "a1", taskId: "t1", path: "main.py" })).toBe(
      "$ write main.py"
    );
  });

  it("falls back to the action type/id when neither is known", () => {
    expect(formatActionCommand({ actionId: "a1", taskId: "t1", type: "run_command" })).toBe(
      "$ run_command a1"
    );
  });
});

describe("transcriptLineFromActionEvent", () => {
  it("returns null for a non-action event type", () => {
    expect(transcriptLineFromActionEvent("run.timeline.validation", { actionId: "a1", taskId: "t1" })).toBeNull();
  });

  it("renders a failed command's real stderr, not the command echoed back as output", () => {
    const line = transcriptLineFromActionEvent("execution.action.failed", {
      actionId: "a1",
      taskId: "t1",
      command: ["cd", "proj", "&&", "pytest"],
      error: "Command 'cd' is not in the allowed list.",
      stderr: "Command 'cd' is not in the allowed list.",
      stepLabel: "Run pytest tests/test_charge.py",
    });

    expect(line?.command).toBe("$ cd proj && pytest");
    expect(line?.tone).toBe("error");
    expect(line?.output).toContain("Command 'cd' is not in the allowed list.");
    expect(line?.stepLabel).toBe("Run pytest tests/test_charge.py");
  });

  it("renders a completed command's real stdout", () => {
    const line = transcriptLineFromActionEvent("execution.action.completed", {
      actionId: "a1",
      taskId: "t1",
      command: ["pytest", "-q"],
      stdout: "1 passed",
    });

    expect(line?.tone).toBe("success");
    expect(line?.output).toBe("1 passed");
  });
});

describe("transcriptLineFromActionResult", () => {
  it("renders a failed action's real error, not a repeated description", () => {
    const line = transcriptLineFromActionResult({
      action_id: "a1",
      status: "failed",
      command: ["cd", "proj", "&&", "pytest"],
      error: "Command 'cd' is not in the allowed list.",
    });

    expect(line.command).toBe("$ cd proj && pytest");
    expect(line.tone).toBe("error");
    expect(line.output).toBe("Command 'cd' is not in the allowed list.");
  });

  it("renders a write action's diff summary", () => {
    const line = transcriptLineFromActionResult({
      action_id: "a1",
      status: "succeeded",
      path: "main.py",
      diff: "--- a\n+++ b\n",
    });

    expect(line.command).toBe("$ write main.py");
    expect(line.output).toBe("--- a\n+++ b\n");
  });

  it("uses the task title as the step label when provided", () => {
    const line = transcriptLineFromActionResult(
      { action_id: "a1", status: "succeeded", path: "main.py" },
      "Creating main.py"
    );

    expect(line.stepLabel).toBe("Creating main.py");
  });

  it("falls back to the raw action id with no task title", () => {
    const line = transcriptLineFromActionResult({ action_id: "a1", status: "succeeded", path: "main.py" });

    expect(line.stepLabel).toBe("a1");
  });
});
