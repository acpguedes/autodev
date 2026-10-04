import { afterEach, describe, expect, it, vi } from "vitest";

import { consumeSseStream } from "../api_v2";

function streamOf(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200 });
}

describe("consumeSseStream", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("delivers frames split across chunks and resolves true", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamOf(["id: 1\nevent: a\ndata: {", '"x":1}\n\n'])));
    const onOpen = vi.fn();
    const seen: string[] = [];

    const ok = await consumeSseStream(
      "/s",
      { signal: new AbortController().signal },
      { onOpen, onFrames: (frames) => frames.forEach((f) => seen.push(`${f.id}:${f.event}:${f.data}`)) },
    );

    expect(ok).toBe(true);
    expect(onOpen).toHaveBeenCalledOnce();
    expect(seen).toEqual(['1:a:{"x":1}']);
  });

  it("resolves false without opening when the server refuses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("no", { status: 500 })));
    const onOpen = vi.fn();
    const ok = await consumeSseStream("/s", { signal: new AbortController().signal }, { onOpen, onFrames: vi.fn() });
    expect(ok).toBe(false);
    expect(onOpen).not.toHaveBeenCalled();
  });
});
