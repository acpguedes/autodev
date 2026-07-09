"use client";

import * as React from "react";

/** A referenceable context target offered by the `@` affordance. */
export type ContextOption = {
  /** Mention token inserted into the prompt (e.g. `@session:abc123`). */
  token: string;
  /** Human-readable label shown in the menu. */
  label: string;
};

/** Props for {@link ChatComposer}. */
export type ChatComposerProps = {
  /** Current composer text (controlled). */
  value: string;
  /** Change handler for the composer text. */
  onChange: (value: string) => void;
  /** Invoked with the trimmed text when the operator sends. */
  onSend: (text: string) => void;
  /** Disables sending while a turn is executing. */
  busy: boolean;
  /** Active provider name (e.g. "stub"), or null while unknown. */
  providerName: string | null;
  /** Active provider model (e.g. "deterministic-stub"), or null. */
  providerModel: string | null;
  /** Placeholder for the textarea. */
  placeholder: string;
  /** Label for the send button. */
  sendLabel: string;
  /** Label for the send button while busy. */
  busyLabel: string;
  /** Accessible label for the `@` context button. */
  contextLabel: string;
  /** Message shown when there are no context options. */
  contextEmptyLabel: string;
  /** Context targets offered by the `@` menu. */
  contextOptions: readonly ContextOption[];
};

/** Maximum auto-grow height of the textarea in CSS pixels. */
const MAX_TEXTAREA_HEIGHT = 220;

/**
 * The chat composer (E17-S1-T2): an auto-growing textarea with a provider
 * chip, an `@context` mention affordance, and Enter-to-send semantics
 * (Shift+Enter inserts a newline), per the redesign prototype.
 *
 * @param props - See {@link ChatComposerProps}.
 * @returns The composer card.
 */
export function ChatComposer({
  value,
  onChange,
  onSend,
  busy,
  providerName,
  providerModel,
  placeholder,
  sendLabel,
  busyLabel,
  contextLabel,
  contextEmptyLabel,
  contextOptions,
}: ChatComposerProps): React.JSX.Element {
  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null);
  const menuRef = React.useRef<HTMLDivElement | null>(null);
  const [menuOpen, setMenuOpen] = React.useState(false);

  /** Resize the textarea to fit its content, capped at the max height. */
  const autoGrow = React.useCallback((): void => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_TEXTAREA_HEIGHT)}px`;
  }, []);

  React.useEffect(() => {
    autoGrow();
  }, [value, autoGrow]);

  // Close the context menu on any pointer press outside of it.
  React.useEffect(() => {
    if (!menuOpen) {
      return;
    }
    function onPointerDown(event: PointerEvent): void {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [menuOpen]);

  /** Send the current text when non-empty and not busy. */
  function send(): void {
    const text = value.trim();
    if (!text || busy) {
      return;
    }
    onSend(text);
  }

  /** Enter sends; Shift+Enter falls through and inserts a newline. */
  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  }

  /** Append a mention token to the prompt and refocus the textarea. */
  function pickContext(token: string): void {
    const separator = value.length > 0 && !value.endsWith(" ") ? " " : "";
    onChange(`${value}${separator}${token} `);
    setMenuOpen(false);
    textareaRef.current?.focus();
  }

  const providerText = providerName
    ? `${providerName}${providerModel ? ` · ${providerModel}` : ""}`
    : null;

  return (
    <div className="rounded-ds-lg border border-ds-line bg-ds-bg-2 p-3 shadow-ds-sm">
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label={placeholder}
        className="max-h-[220px] min-h-[44px] w-full resize-none bg-transparent px-1 py-1.5 text-sm leading-relaxed text-ds-fg placeholder:text-ds-fg-3 focus-visible:outline-none"
      />
      <div className="mt-2 flex items-center gap-2">
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            aria-label={contextLabel}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
            className="flex h-8 w-8 items-center justify-center rounded-ds-sm border border-ds-line text-[15px] font-semibold text-ds-fg-2 transition-colors hover:bg-ds-bg-3 hover:text-ds-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent"
          >
            @
          </button>
          {menuOpen ? (
            <div
              role="menu"
              aria-label={contextLabel}
              className="absolute bottom-10 left-0 z-20 w-64 rounded-ds-md border border-ds-line bg-ds-bg-2 p-1.5 shadow-ds-md"
            >
              {contextOptions.length === 0 ? (
                <p className="px-2 py-1.5 text-xs text-ds-fg-3">{contextEmptyLabel}</p>
              ) : (
                contextOptions.map((option) => (
                  <button
                    key={option.token}
                    type="button"
                    role="menuitem"
                    onClick={() => pickContext(option.token)}
                    className="flex w-full flex-col items-start gap-0.5 rounded-ds-sm px-2 py-1.5 text-left transition-colors hover:bg-ds-bg-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent"
                  >
                    <span className="font-mono text-[11px] text-ds-accent-strong">
                      {option.token}
                    </span>
                    <span className="max-w-full truncate text-xs text-ds-fg-2">{option.label}</span>
                  </button>
                ))
              )}
            </div>
          ) : null}
        </div>
        {providerText ? (
          <span className="rounded-ds-full border border-ds-line bg-ds-bg-3 px-2.5 py-1 font-mono text-[11px] text-ds-fg-2">
            {providerText}
          </span>
        ) : null}
        <button
          type="button"
          onClick={send}
          disabled={busy || value.trim().length === 0}
          className="ml-auto rounded-ds-md bg-ds-accent px-4 py-2 text-[13px] font-semibold text-ds-accent-fg shadow-ds-sm transition-opacity disabled:cursor-default disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent-strong"
        >
          {busy ? busyLabel : sendLabel}
        </button>
      </div>
    </div>
  );
}

export default ChatComposer;
