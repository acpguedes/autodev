"use client";

import { FitAddon } from "@xterm/addon-fit";
import { Terminal, type ITheme } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import * as React from "react";

/** Imperative surface the session logic drives; keeps xterm out of its imports. */
export interface TerminalViewApi {
  /** Write shell output to the screen. */
  write(data: string): void;
  /** Clear the screen and scrollback. */
  reset(): void;
  /** Current grid size. */
  size(): { cols: number; rows: number };
  /** Focus the terminal. */
  focus(): void;
}

/** Props for {@link TerminalView}. */
export interface TerminalViewProps {
  /** Whether the terminal tab is visible; refits and focuses when it becomes so. */
  active: boolean;
  /** Changes when the colour theme changes so the palette is re-read. */
  themeKey: string | undefined;
  /** Called once xterm is constructed. */
  onReady: (api: TerminalViewApi) => void;
  /** Keystrokes typed by the user. */
  onData: (data: string) => void;
  /** Grid size changed. */
  onResize: (cols: number, rows: number) => void;
  /** Accessible name of the terminal region. */
  label: string;
}

/** Read a `--ds-*` HSL-triplet token as a CSS colour. */
function token(name: string, alpha?: number): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!raw) {
    return "";
  }
  return alpha === undefined ? `hsl(${raw})` : `hsl(${raw} / ${alpha})`;
}

/** Build the xterm theme from the design-system tokens so dark mode is honoured. */
function readTheme(): ITheme {
  return {
    background: token("--ds-bg-2"),
    foreground: token("--ds-fg"),
    cursor: token("--ds-accent"),
    cursorAccent: token("--ds-bg-2"),
    selectionBackground: token("--ds-accent", 0.3),
    red: token("--ds-danger"),
    green: token("--ds-success"),
    yellow: token("--ds-warn"),
    blue: token("--ds-accent"),
    brightBlack: token("--ds-fg-3"),
  };
}

/**
 * The xterm.js surface. Loaded only through `next/dynamic({ ssr: false })`
 * because xterm touches `window` at import time and must stay out of the main
 * bundle (E65-S3-T2).
 */
export default function TerminalView(props: TerminalViewProps): React.JSX.Element {
  const { active, themeKey, onReady, onData, onResize, label } = props;
  const hostRef = React.useRef<HTMLDivElement>(null);
  const termRef = React.useRef<Terminal | null>(null);
  const fitRef = React.useRef<FitAddon | null>(null);
  const callbacks = React.useRef({ onData, onResize });
  callbacks.current = { onData, onResize };

  React.useEffect(() => {
    const host = hostRef.current;
    if (!host) {
      return;
    }
    const term = new Terminal({
      cursorBlink: true,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      fontSize: 13,
      scrollback: 5000,
      theme: readTheme(),
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host);
    termRef.current = term;
    fitRef.current = fit;

    const refit = (): void => {
      if (host.clientWidth > 0 && host.clientHeight > 0) {
        fit.fit();
      }
    };
    refit();
    const dataSub = term.onData((d) => callbacks.current.onData(d));
    const resizeSub = term.onResize(({ cols, rows }) => callbacks.current.onResize(cols, rows));
    const observer = new ResizeObserver(refit);
    observer.observe(host);

    onReady({
      write: (data) => term.write(data),
      reset: () => term.reset(),
      size: () => ({ cols: term.cols, rows: term.rows }),
      focus: () => term.focus(),
    });

    return () => {
      observer.disconnect();
      dataSub.dispose();
      resizeSub.dispose();
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
    // onReady is intentionally read once at construction.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    const frame = requestAnimationFrame(() => {
      if (termRef.current) {
        termRef.current.options.theme = readTheme();
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [themeKey]);

  React.useEffect(() => {
    if (active && termRef.current && hostRef.current && hostRef.current.clientWidth > 0) {
      fitRef.current?.fit();
      termRef.current.focus();
    }
  }, [active]);

  return (
    <div
      ref={hostRef}
      role="region"
      aria-label={label}
      data-testid="terminal-host"
      className="h-full w-full overflow-hidden bg-ds-bg-2 p-2"
    />
  );
}
