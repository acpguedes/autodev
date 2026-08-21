import { describe, expect, it } from "vitest";

import {
  applyTimelineEvent,
  emptyTimeline,
  normalizeStageStatus,
  parseRunTimelineStepData,
  timelineStageForEventType,
} from "../timeline";

describe("normalizeStageStatus", () => {
  it("maps known terminal/idle strings to their rendered status", () => {
    expect(normalizeStageStatus("completed")).toBe("done");
    expect(normalizeStageStatus("failed")).toBe("failed");
    expect(normalizeStageStatus("")).toBe("idle");
  });

  it("treats an unrecognized status as running rather than silently idle", () => {
    expect(normalizeStageStatus("in_progress")).toBe("running");
  });
});

describe("timelineStageForEventType", () => {
  it("resolves a run.timeline.* event type to its stage", () => {
    expect(timelineStageForEventType("run.timeline.validation")).toBe("validation");
  });

  it("returns null for a non-timeline event type", () => {
    expect(timelineStageForEventType("flow.run.started")).toBeNull();
  });
});

describe("parseRunTimelineStepData", () => {
  it("decodes a well-formed payload", () => {
    const parsed = parseRunTimelineStepData(
      JSON.stringify({
        stepKey: "task-1",
        actorRole: "coder",
        status: "completed",
        output: "$ pytest -q\n1 passed",
      })
    );
    expect(parsed).toEqual({
      stepKey: "task-1",
      actorRole: "coder",
      status: "completed",
      output: "$ pytest -q\n1 passed",
    });
  });

  it("returns null for malformed JSON or a payload missing required fields", () => {
    expect(parseRunTimelineStepData("not json")).toBeNull();
    expect(parseRunTimelineStepData(JSON.stringify({ stepKey: "task-1" }))).toBeNull();
  });
});

describe("applyTimelineEvent", () => {
  it("updates the matching stage's status/actor and sets its initial output", () => {
    const states = applyTimelineEvent(emptyTimeline(), "run.timeline.patch", {
      stepKey: "task-1",
      actorRole: "coder",
      status: "completed",
      output: "wrote backend/payments/charge.py",
    });
    const patch = states.find((state) => state.stage === "patch");
    expect(patch).toMatchObject({
      status: "done",
      actorRole: "coder",
      output: "wrote backend/payments/charge.py",
    });
  });

  it("accumulates output across multiple events on the same stage (E42-S5-T3)", () => {
    let states = applyTimelineEvent(emptyTimeline(), "run.timeline.validation", {
      stepKey: "task-1",
      actorRole: "validator",
      status: "completed",
      output: "$ pytest -q\n1 passed",
    });
    states = applyTimelineEvent(states, "run.timeline.validation", {
      stepKey: "task-2",
      actorRole: "validator",
      status: "failed",
      output: "$ mypy .\n1 error",
    });

    const validation = states.find((state) => state.stage === "validation");
    expect(validation?.output).toBe("$ pytest -q\n1 passed\n\n$ mypy .\n1 error");
    // The later event's status/actor win -- only output accumulates.
    expect(validation?.status).toBe("failed");
  });

  it("leaves an existing stage's output untouched when a later event's output is empty", () => {
    let states = applyTimelineEvent(emptyTimeline(), "run.timeline.planning", {
      stepKey: "task-1",
      actorRole: "planner",
      status: "running",
      output: "drafting plan...",
    });
    states = applyTimelineEvent(states, "run.timeline.planning", {
      stepKey: "task-1",
      actorRole: "planner",
      status: "completed",
      output: "",
    });

    const planning = states.find((state) => state.stage === "planning");
    expect(planning?.output).toBe("drafting plan...");
    expect(planning?.status).toBe("done");
  });

  it("leaves the states unchanged for a non-timeline event type", () => {
    const seed = emptyTimeline();
    const result = applyTimelineEvent(seed, "flow.run.started", {
      stepKey: "x",
      actorRole: "coder",
      status: "completed",
      output: "irrelevant",
    });
    expect(result).toEqual(seed);
  });
});
