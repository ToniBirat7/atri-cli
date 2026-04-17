'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import type { Message } from '@/lib/useChat';

interface ChatMessageProps {
  message: Message;
  isStreaming: boolean;
  isLast: boolean;
}

function UserIcon() {
  return (
    <div className="w-7 h-7 rounded-full bg-accent flex items-center justify-center shrink-0">
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="white"
        strokeWidth="2"
      >
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
        <circle cx="12" cy="7" r="4" />
      </svg>
    </div>
  );
}

function AIIcon() {
  return (
    <div className="w-7 h-7 rounded-full bg-bg-tertiary border border-border flex items-center justify-center shrink-0">
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth="2"
      >
        <path d="M12 2L2 7l10 5 10-5-10-5z" />
        <path d="M2 17l10 5 10-5" />
        <path d="M2 12l10 5 10-5" />
      </svg>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
  };

  return (
    <button
      onClick={handleCopy}
      className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-bg-hover text-text-muted hover:text-text-secondary"
      title="Copy message"
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
      </svg>
    </button>
  );
}

export default function ChatMessage({
  message,
  isStreaming,
  isLast,
}: ChatMessageProps) {
  const isUser = message.role === 'user';
  const showCursor =
    !isUser && isStreaming && isLast && message.content.length > 0;
  const showLoading =
    !isUser && isLast && isStreaming && message.content.length === 0;

  return (
    <div className={`group py-5 ${isUser ? '' : ''}`}>
      <div className="max-w-3xl mx-auto px-4 flex gap-4">
        <div className="mt-1">{isUser ? <UserIcon /> : <AIIcon />}</div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-text-secondary">
              {isUser ? 'You' : 'Assistant'}
            </span>
            <CopyButton text={message.content} />
          </div>

          {isUser ? (
            <div className="text-text-primary leading-relaxed whitespace-pre-wrap">
              {message.content}
            </div>
          ) : showLoading ? (
            <div className="flex items-center gap-1.5 py-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce [animation-delay:0ms]" />
              <div className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce [animation-delay:150ms]" />
              <div className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce [animation-delay:300ms]" />
            </div>
          ) : (
            <div
              className={`prose prose-sm max-w-none ${showCursor ? 'typing-cursor' : ''}`}
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
