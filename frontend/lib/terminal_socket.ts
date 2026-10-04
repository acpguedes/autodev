/**
 * Transport for the interactive terminal (E65-S3): socket URL derivation and
 * frame encoding/decoding for `WS /v2/terminal/{terminal_id}`.
 *
 * Deliberately free of any xterm import so it stays jsdom/node-testable, the
 * way `lib/execution_events.ts` is. The socket authenticates with the same
 * session cookie as the REST client, so no token is ever placed in the URL.
 */

import { buildUrl, requestJson } from "./api_ext";

/** Close code: the caller is not authenticated. */
export const CLOSE_UNAUTHENTICATED = 4401;
/** Close code: the terminal is disabled or the caller is forbidden. */
export const CLOSE_FORBIDDEN = 4403;

/** Frames the server sends to the client. */
export type TerminalServerFrame =
  | { type: "info"; projectRoot: string; terminalId: string }
  | { type: "output"; data: string }
  | { type: "exit"; code: number | null };

/** Response of `GET /v2/terminal/status`. */
export interface TerminalStatus {
  enabled: boolean;
}

/**
 * Map an HTTP(S) URL (or root-relative path) to its WebSocket equivalent.
 *
 * @param httpUrl - Absolute `http(s):` URL, or a root-relative path.
 * @param origin - Page origin used to resolve a relative path.
 * @returns The `ws:`/`wss:` URL.
 */
export function toWebSocketUrl(httpUrl: string, origin: string): string {
  const url = new URL(httpUrl, origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

/**
 * Build the socket URL for one terminal id from the REST client's base.
 *
 * @param terminalId - Client-generated terminal id.
 * @param origin - Page origin; defaults to `window.location.origin`.
 * @returns The `ws(s)://.../v2/terminal/{id}` URL.
 */
export function terminalSocketUrl(
  terminalId: string,
  origin: string = typeof window === "undefined" ? "http://localhost" : window.location.origin
): string {
  return toWebSocketUrl(buildUrl(`v2/terminal/${encodeURIComponent(terminalId)}`), origin);
}

/**
 * Fetch whether the terminal feature is enabled server-side.
 *
 * @returns The status payload.
 * @throws Error when the request fails.
 */
export function getTerminalStatus(): Promise<TerminalStatus> {
  return requestJson<TerminalStatus>("v2/terminal/status");
}

/** Encode keystrokes as an `input` frame. */
export function encodeInput(data: string): string {
  return JSON.stringify({ type: "input", data });
}

/** Encode a viewport change as a `resize` frame (dimensions clamped to >= 1). */
export function encodeResize(cols: number, rows: number): string {
  return JSON.stringify({
    type: "resize",
    cols: Math.max(1, Math.floor(cols)),
    rows: Math.max(1, Math.floor(rows)),
  });
}

/**
 * Decode a server frame, rejecting anything that does not match the contract.
 *
 * @param raw - Message payload from the socket.
 * @returns The typed frame, or `null` when malformed or of an unknown type.
 */
export function parseServerFrame(raw: unknown): TerminalServerFrame | null {
  if (typeof raw !== "string") {
    return null;
  }
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const frame = value as Record<string, unknown>;
  if (frame.type === "output" && typeof frame.data === "string") {
    return { type: "output", data: frame.data };
  }
  if (
    frame.type === "info" &&
    typeof frame.projectRoot === "string" &&
    typeof frame.terminalId === "string"
  ) {
    return { type: "info", projectRoot: frame.projectRoot, terminalId: frame.terminalId };
  }
  if (frame.type === "exit" && (frame.code === null || typeof frame.code === "number")) {
    return { type: "exit", code: frame.code };
  }
  return null;
}

/**
 * Whether the server's bound project root differs from the active project, in
 * which case the stored terminal id is stale and must be discarded.
 */
export function isProjectMismatch(infoProjectRoot: string, activeProjectRoot: string): boolean {
  return infoProjectRoot !== activeProjectRoot;
}

/** Generate a fresh client-side terminal id. */
export function generateTerminalId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Callbacks for {@link openTerminalSocket}. */
export interface TerminalSocketHandlers {
  /** The socket opened; the caller should send its initial resize. */
  onOpen?(): void;
  /** A valid server frame arrived. */
  onFrame(frame: TerminalServerFrame): void;
  /** The socket closed with the given close code. */
  onClose(code: number): void;
}

/** Handle returned by {@link openTerminalSocket}. */
export interface TerminalSocketHandle {
  /** Send keystrokes to the shell. */
  sendInput(data: string): void;
  /** Send a viewport resize. */
  sendResize(cols: number, rows: number): void;
  /** Close the socket (no further callbacks). */
  close(): void;
}

/**
 * Open the terminal socket and wire frame decoding.
 *
 * @param url - Socket URL from {@link terminalSocketUrl}.
 * @param handlers - Frame and close callbacks.
 * @param socketFactory - WebSocket constructor override for tests.
 * @returns A handle to send frames or close. Sends before the socket is open
 *   are dropped, as the shell is not attached yet.
 */
export function openTerminalSocket(
  url: string,
  handlers: TerminalSocketHandlers,
  socketFactory: (url: string) => WebSocket = (u) => new WebSocket(u)
): TerminalSocketHandle {
  const socket = socketFactory(url);
  let closed = false;
  socket.onopen = () => {
    if (!closed) {
      handlers.onOpen?.();
    }
  };
  socket.onmessage = (event: MessageEvent) => {
    const frame = parseServerFrame(event.data);
    if (frame && !closed) {
      handlers.onFrame(frame);
    }
  };
  socket.onclose = (event: CloseEvent) => {
    if (!closed) {
      closed = true;
      handlers.onClose(event.code);
    }
  };
  const send = (payload: string): void => {
    if (!closed && socket.readyState === 1) {
      socket.send(payload);
    }
  };
  return {
    sendInput: (data) => send(encodeInput(data)),
    sendResize: (cols, rows) => send(encodeResize(cols, rows)),
    close: () => {
      closed = true;
      socket.close();
    },
  };
}
