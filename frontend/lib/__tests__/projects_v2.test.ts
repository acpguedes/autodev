import { afterEach, describe, expect, it, vi } from "vitest";

import { createProjectV2, initProjectV2, listProjectsV2, openProjectV2 } from "../projects_v2";

function mockFetch(body: unknown) {
  const fn = vi.fn().mockResolvedValue({ ok: true, json: async () => body });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("projects_v2 client", () => {
  it("lists projects", async () => {
    const fetchMock = mockFetch({ schemaVersion: "2", items: [], activeProjectId: null });
    expect((await listProjectsV2()).activeProjectId).toBeNull();
    expect(String(fetchMock.mock.calls[0][0])).toContain("v2/projects");
  });

  it.each([
    ["open", openProjectV2, "v2/projects/open"],
    ["init", initProjectV2, "v2/projects/init"],
    ["create", createProjectV2, "v2/projects/create"],
  ] as const)("posts the root for %s", async (_name, fn, path) => {
    const fetchMock = mockFetch({ projectId: "p", name: "n", rootPath: "/r", active: true });
    await fn("/r");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(path);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).root).toBe("/r");
  });
});
