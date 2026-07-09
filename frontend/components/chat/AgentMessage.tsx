"use client";

import * as React from "react";

/** Props for {@link AgentMessage}. */
export type AgentMessageProps = {
  /** Who authored the message. */
  speaker: "user" | "agent";
  /** Display label for the role tag (e.g. "You", "Planner", "Coder"). */
  roleLabel: string;
  /** Message body; whitespace is preserved. */
  content: string;
};

/**
 * One message in the editorial chat stream (E17-S1-T1).
 *
 * Agent replies carry an accent role tag (Planner/Coder/Validator, ...);
 * the operator's own messages are visually distinct via a stronger card
 * background and a neutral tag, matching the redesign prototype's calm,
 * card-per-message rhythm.
 *
 * @param props - See {@link AgentMessageProps}.
 * @returns The message card as a list item.
 */
export function AgentMessage({ speaker, roleLabel, content }: AgentMessageProps): React.JSX.Element {
  const isUser = speaker === "user";
  return (
    <li
      className={
        isUser
          ? "rounded-ds-md border border-ds-line bg-ds-bg-2 p-4 shadow-ds-sm"
          : "rounded-ds-md border border-ds-line bg-ds-bg-3 p-4"
      }
    >
      <span
        className={
          "text-[11px] font-bold uppercase tracking-[0.05em] " +
          (isUser ? "text-ds-fg-2" : "text-ds-accent-strong")
        }
      >
        {roleLabel}
      </span>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-ds-fg-2">{content}</p>
    </li>
  );
}

export default AgentMessage;
