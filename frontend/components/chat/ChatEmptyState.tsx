"use client";

import * as React from "react";

/** One clickable task suggestion in the chat empty state. */
export type ChatSuggestion = {
  /** Decorative glyph shown beside the suggestion. */
  icon: string;
  /** Suggestion text; inserted into the composer when picked. */
  text: string;
};

/** Props for {@link ChatEmptyState}. */
export type ChatEmptyStateProps = {
  /** Serif display headline (prototype: "What are we building today?"). */
  headline: string;
  /** Supporting sentence under the headline. */
  subtitle: string;
  /** Task suggestions rendered as a card grid (prototype ships four). */
  suggestions: readonly ChatSuggestion[];
  /** Invoked with the suggestion text when a card is activated. */
  onPick: (text: string) => void;
};

/**
 * Empty state for a fresh chat session (E17-S1-T1): an editorial serif
 * headline and a grid of clickable task-suggestion cards.
 *
 * @param props - See {@link ChatEmptyStateProps}.
 * @returns The centered empty-state block.
 */
export function ChatEmptyState({
  headline,
  subtitle,
  suggestions,
  onPick,
}: ChatEmptyStateProps): React.JSX.Element {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-16 text-center">
      <h2 className="max-w-[520px] font-serif text-[34px] font-medium leading-tight tracking-[-0.015em] text-ds-fg">
        {headline}
      </h2>
      <p className="mt-3 max-w-[420px] text-sm leading-relaxed text-ds-fg-2">{subtitle}</p>
      <ul className="mt-8 grid w-full max-w-[560px] grid-cols-1 gap-3 sm:grid-cols-2">
        {suggestions.map((suggestion) => (
          <li key={suggestion.text}>
            <button
              type="button"
              onClick={() => onPick(suggestion.text)}
              className="flex w-full items-center gap-3 rounded-ds-md border border-ds-line bg-ds-bg-2 px-4 py-3.5 text-left text-[13px] font-medium text-ds-fg shadow-ds-sm transition-colors hover:border-ds-line-strong hover:bg-ds-bg-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent"
            >
              <span
                aria-hidden="true"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-ds-sm bg-ds-accent/10 text-[15px] text-ds-accent-strong"
              >
                {suggestion.icon}
              </span>
              {suggestion.text}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default ChatEmptyState;
