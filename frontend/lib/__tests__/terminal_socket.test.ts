// E65-S3/S4: socket URL mapping, frame encoding/decoding and stale-id handling
// for the interactive terminal. No xterm import by design.

import { describe, expect, it, vi } from "vitest";

import {
  CLOSE_FORBIDDEN,
  encodeInput,
  encodeResize,
  generateTerminalId,
  isProjectMismatch,
  openTerminalSocket,
  parseServerFrame,
  terminalSocketUrl,
  toWebSocketUrl,
} from "../terminal_socket";

describe("socket URL mapping", () => {
  it("maps http to ws and https to wss", () => {
    expect(toWebSocketUrl("http://localhost:8000/v2/terminal/a", "http://x")).toBe(
      "ws://localhost:8000/v2/terminal/a"
    );
    expect(toWebSocketUrl("https://api.example.com/v2/terminal/a", "https://x")).toBe(
      "wss://api.example.com/v2/terminal/a"
    );
  });

  it("resolves a root-relative REST path against the page origin", () => {
    expect(terminalSocketUrl("abc", "https://app.example.com")).toBe(
      "wss://app.example.com/v2/terminal/abc"
    );
    expect(terminalSocketUrl("a b/c", "http://localhost:3000")).toBe(
      "ws://localhost:3000/v2/terminal/a%20b%2Fc"
    );
  });

  it("never puts a token in the URL", () => {
    expect(terminalSocketUrl("abc", "http://localhost")).not.toContain("token");
  });
});

describe("frame encoding", () => {
  it("encodes input and resize frames", () => {
    expect(JSON.parse(encodeInput("ls\r"))).toEqual({ type: "input", data: "ls\r" });
    expect(JSON.parse(encodeResize(80.9, 24))).toEqual({ type: "resize", cols: 80, rows: 24 });
    expect(JSON.parse(encodeResize(0, -3))).toEqual({ type: "resize", cols: 1, rows: 1 });
  });

  it("parses valid server frames and rejects malformed ones", () => {
    expect(parseServerFrame('{"type":"output","data":"hi"}')).toEqual({ type: "output", data: "hi" });
    expect(parseServerFrame('{"type":"exit","code":null}')).toEqual({ type: "exit", code: null });
    expect(parseServerFrame('{"type":"info","projectRoot":"/p","terminalId":"t"}')).toEqual({
      type: "info",
      projectRoot: "/p",
      terminalId: "t",
    });
    expect(parseServerFrame("not json")).toBeNull();
    expect(parseServerFrame('{"type":"output"}')).toBeNull();
    expect(parseServerFrame('{"type":"nope"}')).toBeNull();
    expect(parseServerFrame(new ArrayBuffer(1))).toBeNull();
  });
});

describe("openTerminalSocket", () => {
  function fakeSocket() {
    return {
      readyState: 0,
      sent: [] as string[],
      closed: false,
      onopen: null as (() => void) | null,
      onmessage: null as ((e: { data: unknown }) => void) | null,
      onclose: null as ((e: { code: number }) => void) | null,
      send(p: string) {
        this.sent.push(p);
      },
      close() {
        this.closed = true;
      },
    };
  }

  it("drops sends before open, then emits input/resize frames", () => {
    const sock = fakeSocket();
    const handle = openTerminalSocket(
      "ws://x",
      { onFrame: vi.fn(), onClose: vi.fn() },
      () => sock as never
    );
    handle.sendInput("a");
    expect(sock.sent).toEqual([]);
    sock.readyState = 1;
    handle.sendInput("a");
    handle.sendResize(100, 30);
    expect(sock.sent.map((s) => JSON.parse(s))).toEqual([
      { type: "input", data: "a" },
      { type: "resize", cols: 100, rows: 30 },
    ]);
  });

  it("delivers frames and the close code, and goes silent after close()", () => {
    const sock = fakeSocket();
    const onFrame = vi.fn();
    const onClose = vi.fn();
    const handle = openTerminalSocket("ws://x", { onFrame, onClose }, () => sock as never);
    sock.onmessage?.({ data: '{"type":"output","data":"z"}' });
    expect(onFrame).toHaveBeenCalledWith({ type: "output", data: "z" });
    sock.onclose?.({ code: CLOSE_FORBIDDEN });
    expect(onClose).toHaveBeenCalledWith(4403);
    handle.close();
    sock.onmessage?.({ data: '{"type":"output","data":"late"}' });
    expect(onFrame).toHaveBeenCalledTimes(1);
  });
});

describe("stale terminal id", () => {
  it("flags a project-root mismatch and accepts a match", () => {
    expect(isProjectMismatch("/a", "/b")).toBe(true);
    expect(isProjectMismatch("/a", "/a")).toBe(false);
  });

  it("generates distinct ids", () => {
    expect(generateTerminalId()).not.toBe(generateTerminalId());
  });
});
