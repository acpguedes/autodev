import { describe, expect, it } from "vitest";

import { ensureLeadingSlash, joinUrl, stripTrailingSlash } from "../url";

describe("url helpers", () => {
  it("strips trailing slashes", () => {
    expect(stripTrailingSlash("http://x/")).toBe("http://x");
    expect(stripTrailingSlash("http://x///")).toBe("http://x");
    expect(stripTrailingSlash("http://x")).toBe("http://x");
  });

  it("ensures exactly one leading slash", () => {
    expect(ensureLeadingSlash("skills")).toBe("/skills");
    expect(ensureLeadingSlash("/skills")).toBe("/skills");
  });

  it("joins base and path without double slashes", () => {
    expect(joinUrl("http://localhost:8000/", "skills")).toBe("http://localhost:8000/skills");
    expect(joinUrl("http://localhost:8000", "/skills")).toBe("http://localhost:8000/skills");
    expect(joinUrl("", "skills")).toBe("/skills");
  });
});
