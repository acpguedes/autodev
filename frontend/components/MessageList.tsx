"use client";

export type Message = {
  author: string;
  content: string;
};

type MessageListProps = {
  messages: Message[];
};

export function MessageList({ messages }: MessageListProps) {
  return (
    <div className="flex min-h-[340px] flex-1 flex-col gap-4 overflow-y-auto pr-1.5">
      {messages.map((message, index) => (
        <div
          className="rounded-ds-md border border-ds-line bg-ds-bg-3 p-4"
          key={`${message.author}-${index}`}
        >
          <span className="text-[11px] font-bold uppercase tracking-[0.05em] text-ds-accent-strong">
            {message.author}
          </span>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-ds-fg-2">
            {message.content}
          </p>
        </div>
      ))}
    </div>
  );
}

export default MessageList;
