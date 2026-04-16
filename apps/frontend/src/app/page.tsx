'use client';

import { useRef, useEffect, useState } from 'react';
import { useChat } from '@/lib/useChat';
import ChatMessage from '@/components/ChatMessage';
import ChatInput from '@/components/ChatInput';
import EmptyState from '@/components/EmptyState';

export default function Home() {
  const { messages, isStreaming, sendMessage, stopStreaming, clearChat } =
    useChat();
  const [allowedDirectory, setAllowedDirectory] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const hasMessages = messages.length > 0;

  return (
    <div className="h-dvh flex flex-col">
      {/* Header */}
      <header className="flex-shrink-0 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-4 h-12 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-lg bg-[var(--color-accent)]/10 flex items-center justify-center">
              <svg
                width="12"
                height="12"
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
            <span className="text-sm font-medium text-[var(--color-text-primary)]">
              Kanoon Box
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--color-bg-tertiary)] text-[var(--color-text-muted)] border border-[var(--color-border)]">
              Gemma 4 E2B
            </span>
          </div>

          <div className="hidden md:flex items-center gap-2 w-[28rem]">
            <input
              value={allowedDirectory}
              onChange={(e) => setAllowedDirectory(e.target.value)}
              placeholder="Allowed directory for MCP tools"
              className="w-full text-xs px-2 py-1 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)]"
            />
          </div>

          {hasMessages && (
            <button
              onClick={clearChat}
              className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors flex items-center gap-1.5 px-2 py-1 rounded-lg hover:bg-[var(--color-bg-hover)]"
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M12 5v14M5 12h14" />
              </svg>
              New chat
            </button>
          )}
        </div>
      </header>

      {/* Demo notice banner */}
      <div className="flex-shrink-0 bg-[var(--color-accent)]/10 border-b border-[var(--color-accent)]/20 px-4 py-1.5">
        <p className="max-w-3xl mx-auto text-[11px] text-[var(--color-accent)]">
          RAG Demo Mode — Paste legal context with your question. No retrieval
          pipeline is connected.
        </p>
      </div>

      {/* Messages area */}
      {hasMessages ? (
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="divide-y divide-[var(--color-border)]/50">
            {messages.map((msg, i) => (
              <ChatMessage
                key={msg.id}
                message={msg}
                isStreaming={isStreaming}
                isLast={i === messages.length - 1}
              />
            ))}
          </div>
          <div ref={bottomRef} className="h-4" />
        </div>
      ) : (
        <EmptyState onSuggestion={sendMessage} />
      )}

      {/* Input */}
      <ChatInput
        onSend={(message) => sendMessage(message, allowedDirectory)}
        onStop={stopStreaming}
        isStreaming={isStreaming}
      />
    </div>
  );
}
