"use client";

import { useState } from "react";

import { useTranslations } from "@/lib/i18n";

export type Message = {
  author: string;
  content: string;
};

type MessageListProps = {
  messages: Message[];
};

/** Author label marking a message as the operator's own (E42-S4). */
const USER_AUTHOR = "You";

/** Content length above which a message starts collapsed (E42-S4-T2). */
const COLLAPSE_THRESHOLD = 480;

function ChatBubble({ message }: { message: Message }) {
  const { t } = useTranslations();
  const isUser = message.author === USER_AUTHOR;
  const isLong = message.content.length > COLLAPSE_THRESHOLD;
  const [collapsed, setCollapsed] = useState(isLong);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`flex max-w-[85%] flex-col gap-2 rounded-ds-md border p-4 sm:max-w-[75%] ${
          isUser
            ? "border-ds-accent/30 bg-ds-accent/10"
            : "border-ds-line bg-ds-bg-3"
        }`}
      >
        <span
          className={`text-[11px] font-bold uppercase tracking-[0.05em] ${
            isUser ? "text-ds-accent-strong" : "text-ds-fg-2"
          }`}
        >
          {message.author}
        </span>
        <p
          className={`whitespace-pre-wrap text-sm leading-relaxed text-ds-fg-2 ${
            collapsed ? "line-clamp-6" : ""
          }`}
        >
          {message.content}
        </p>
        {isLong && (
          <button
            type="button"
            onClick={() => setCollapsed((current) => !current)}
            className="self-start text-xs font-medium text-ds-accent-strong hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ds-accent"
          >
            {collapsed ? t("chat.message.showMore") : t("chat.message.showLess")}
          </button>
        )}
      </div>
    </div>
  );
}

export function MessageList({ messages }: MessageListProps) {
  return (
    <div className="flex flex-col gap-4 pr-1.5">
      {messages.map((message, index) => (
        <ChatBubble message={message} key={`${message.author}-${index}`} />
      ))}
    </div>
  );
}

export default MessageList;
