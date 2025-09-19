"use client";

import { Fragment } from "react";

export type Message = {
  author: string;
  content: string;
};

type MessageListProps = {
  messages: Message[];
};

export function MessageList({ messages }: MessageListProps) {
  return (
    <div className="message-list">
      {messages.map((message, index) => (
        <Fragment key={`${message.author}-${index}`}>
          <div className="message">
            <span className="message__author">{message.author}</span>
            <p className="message__content">{message.content}</p>
          </div>
        </Fragment>
      ))}
    </div>
  );
}

export default MessageList;
