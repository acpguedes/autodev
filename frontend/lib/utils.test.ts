import { describe, expect, it } from "vitest";

import { formatRelativeTime, statusVariant } from "./utils";

describe("formatRelativeTime", () => {
  const now = new Date("2026-07-08T12:00:00.000Z").getTime();

  it("returns 'unknown' for falsy input", () => {
    expect(formatRelativeTime(undefined, now)).toBe("unknown");
    expect(formatRelativeTime(null, now)).toBe("unknown");
    expect(formatRelativeTime("", now)).toBe("unknown");
  });

  it("returns 'unknown' for an unparseable timestamp", () => {
    expect(formatRelativeTime("not-a-date", now)).toBe("unknown");
  });

  it("returns 'just now' for timestamps under a minute old", () => {
    const thirtySecondsAgo = new Date(now - 30 * 1000).toISOString();
    expect(formatRelativeTime(thirtySecondsAgo, now)).toBe("just now");
  });

  it("returns 'just now' for timestamps in the future", () => {
    const inTheFuture = new Date(now + 60 * 1000).toISOString();
    expect(formatRelativeTime(inTheFuture, now)).toBe("just now");
  });

  it("formats minutes, hours, days, months, and years", () => {
    expect(formatRelativeTime(new Date(now - 5 * 60 * 1000).toISOString(), now)).toBe("5m ago");
    expect(formatRelativeTime(new Date(now - 3 * 3600 * 1000).toISOString(), now)).toBe("3h ago");
    expect(formatRelativeTime(new Date(now - 2 * 86400 * 1000).toISOString(), now)).toBe("2d ago");
    expect(formatRelativeTime(new Date(now - 2 * 2592000 * 1000).toISOString(), now)).toBe(
      "2mo ago"
    );
    expect(formatRelativeTime(new Date(now - 2 * 31536000 * 1000).toISOString(), now)).toBe(
      "2y ago"
    );
  });
});

describe("statusVariant", () => {
  it("maps failure-like statuses to destructive", () => {
    expect(statusVariant("failed")).toBe("destructive");
    expect(statusVariant("error")).toBe("destructive");
    expect(statusVariant("rejected")).toBe("destructive");
  });

  it("maps success-like statuses to default", () => {
    expect(statusVariant("completed")).toBe("default");
    expect(statusVariant("approved")).toBe("default");
  });

  it("maps in-progress statuses to secondary", () => {
    expect(statusVariant("running")).toBe("secondary");
  });

  it("falls back to outline for unrecognized statuses", () => {
    expect(statusVariant("pending")).toBe("outline");
  });
});
