"use client";

import { useState, useRef, useEffect, type KeyboardEvent } from "react";

interface ChatInputProps {
  onSend: (message: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export default function ChatInput({ onSend, onStop, isStreaming, disabled }: ChatInputProps) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!isStreaming) {
      textareaRef.current?.focus();
    }
  }, [isStreaming]);

  const handleSubmit = () => {
    const trimmed = input.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setInput("");

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (isStreaming) return;
      handleSubmit();
    }
  };

  return (
    <div className="border-t border-[var(--color-border)] bg-[var(--color-bg-primary)]">
      <div className="max-w-3xl mx-auto px-4 py-3">
        <div className="relative flex items-end gap-2 bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-2xl px-4 py-3 focus-within:border-[var(--color-accent)]/50 transition-colors">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message Kanoon Box..."
            rows={1}
            className="flex-1 bg-transparent resize-none outline-none text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] max-h-48 leading-relaxed text-sm"
            disabled={disabled}
          />

          {isStreaming ? (
            <button
              onClick={onStop}
              className="flex-shrink-0 w-8 h-8 rounded-lg bg-[var(--color-text-secondary)] hover:bg-[var(--color-text-primary)] transition-colors flex items-center justify-center"
              title="Stop generating"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="var(--color-bg-primary)">
                <rect x="4" y="4" width="16" height="16" rx="2" />
              </svg>
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={!input.trim() || disabled}
              className="flex-shrink-0 w-8 h-8 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] disabled:opacity-30 disabled:cursor-not-allowed transition-all flex items-center justify-center"
              title="Send message"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </button>
          )}
        </div>

        <p className="text-[10px] text-[var(--color-text-muted)] text-center mt-2">
          यो जानकारी मार्गदर्शनका लागि मात्र हो, कानूनी सल्लाह होइन। | Gemma 4 E2B via llama.cpp | Toll-free: 1660-01-333-55
        </p>
      </div>
    </div>
  );
}
