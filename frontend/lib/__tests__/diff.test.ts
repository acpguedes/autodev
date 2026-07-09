import { describe, expect, it } from "vitest";

import { foldDiffToUpdatedContent, parseUnifiedDiff } from "../diff";

const SAMPLE_DIFF = [
  "--- a/backend/api/middleware/rate_limit.py",
  "+++ b/backend/api/middleware/rate_limit.py",
  "@@ -1,3 +1,4 @@",
  " import time",
  "+import logging",
  "-DEFAULT_LIMIT = 10",
  "+DEFAULT_LIMIT = 100",
  " ",
].join("\n");

describe("parseUnifiedDiff", () => {
  it("returns an empty list for an empty diff", () => {
    expect(parseUnifiedDiff("")).toEqual([]);
  });

  it("classifies header, hunk, add, del, and context rows", () => {
    const lines = parseUnifiedDiff(SAMPLE_DIFF);
    expect(lines.map((line) => line.kind)).toEqual([
      "header",
      "header",
      "hunk",
      "context",
      "add",
      "del",
      "add",
      "context",
    ]);
  });

  it("numbers only add/context rows against the new file, starting at the hunk's +line", () => {
    const lines = parseUnifiedDiff(SAMPLE_DIFF);
    const numbered = lines.map((line) => line.newLineNo);
    // header, header, hunk have no line number.
    expect(numbered.slice(0, 3)).toEqual([null, null, null]);
    // "import time" (context) -> 1, "import logging" (add) -> 2,
    // "DEFAULT_LIMIT = 10" (del) -> null, "DEFAULT_LIMIT = 100" (add) -> 3,
    // trailing context -> 4.
    expect(numbered.slice(3)).toEqual([1, 2, null, 3, 4]);
  });

  it("strips the leading +/- marker from add/del text", () => {
    const lines = parseUnifiedDiff(SAMPLE_DIFF);
    const add = lines.find((line) => line.kind === "add" && line.text.includes("logging"));
    const del = lines.find((line) => line.kind === "del");
    expect(add?.text).toBe("import logging");
    expect(del?.text).toBe("DEFAULT_LIMIT = 10");
  });

  it("ignores 'no newline at end of file' marker rows", () => {
    const diff = `${SAMPLE_DIFF}\n\\ No newline at end of file`;
    const lines = parseUnifiedDiff(diff);
    expect(lines.some((line) => line.text.includes("No newline"))).toBe(false);
  });
});

describe("foldDiffToUpdatedContent", () => {
  it("reconstructs the new-file content from add/context rows", () => {
    expect(foldDiffToUpdatedContent(SAMPLE_DIFF)).toBe(
      ["import time", "import logging", "DEFAULT_LIMIT = 100", ""].join("\n")
    );
  });

  it("returns an empty string for an empty diff", () => {
    expect(foldDiffToUpdatedContent("")).toBe("");
  });
});
