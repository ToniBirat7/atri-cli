'use client';

import { useEffect, useState } from 'react';
import ChatInput from '@/components/ChatInput';
import ChatMessage from '@/components/ChatMessage';
import EmptyState from '@/components/EmptyState';
import WorkspaceAccessPanel from '@/components/WorkspaceAccessPanel';
import { ToastContainer, useToast } from '@/components/Toast';
import { useChat } from '@/lib/useChat';

const quickPrompts = [
  'Summarize the architecture of this project in plain language.',
  'Draft a concise implementation plan for the next sprint.',
  'Explain how the current streaming pipeline works end to end.',
  'Review this codebase for production readiness risks.',
];

const LOCAL_STORAGE_ALLOWED_DIRECTORY_KEY = 'tarbar.allowedDirectory';
const DEFAULT_ALLOWED_DIRECTORY =
  process.env.NEXT_PUBLIC_DEFAULT_ALLOWED_DIRECTORY?.trim() ?? '';

function StatusBadge({ phase, detail }: { phase: string; detail: string }) {
  const colors: Record<string, string> = {
    idle: 'bg-white/10 text-white/80 border-white/10',
    thinking: 'bg-sky-400/10 text-sky-200 border-sky-400/20',
    tool: 'bg-amber-400/10 text-amber-200 border-amber-400/20',
    finalizing: 'bg-emerald-400/10 text-emerald-200 border-emerald-400/20',
    error: 'bg-rose-400/10 text-rose-200 border-rose-400/20',
  };

  return (
    <div
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${colors[phase] ?? colors.idle}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      <span className="font-medium capitalize">{phase}</span>
      <span className="hidden text-white/70 sm:inline">{detail}</span>
    </div>
  );
}

function SidebarCard({
  title,
  value,
  description,
}: {
  title: string;
  value: string;
  description: string;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4 shadow-[0_18px_60px_rgba(0,0,0,0.22)] backdrop-blur-sm">
      <div className="text-[11px] uppercase tracking-[0.24em] text-white/45">
        {title}
      </div>
      <div className="mt-2 text-lg font-semibold text-white">{value}</div>
      <div className="mt-1 text-sm leading-6 text-white/60">{description}</div>
    </div>
  );
}

export default function Home() {
  const [lastUpdated, setLastUpdated] = useState('Live');
  const [allowedDirectory, setAllowedDirectory] = useState('');
  const [isDirectoryReady, setIsDirectoryReady] = useState(false);
  const {
    messages,
    isStreaming,
    sendMessage,
    stopStreaming,
    clearChat,
    streamStatus,
    activityFeed,
  } = useChat();
  const { toasts, removeToast, infoToast } = useToast();

  useEffect(() => {
    const storedAllowedDirectory = window.localStorage.getItem(
      LOCAL_STORAGE_ALLOWED_DIRECTORY_KEY,
    );

    if (storedAllowedDirectory !== null) {
      setAllowedDirectory(storedAllowedDirectory);
      setIsDirectoryReady(true);
      return;
    }

    setAllowedDirectory(DEFAULT_ALLOWED_DIRECTORY);
    setIsDirectoryReady(true);
  }, []);

  useEffect(() => {
    setLastUpdated(
      new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      }),
    );
  }, [messages.length, activityFeed.length, streamStatus.detail]);

  useEffect(() => {
    if (!isDirectoryReady) {
      return;
    }

    window.localStorage.setItem(
      LOCAL_STORAGE_ALLOWED_DIRECTORY_KEY,
      allowedDirectory,
    );
  }, [allowedDirectory, isDirectoryReady]);

  const hasConversation = messages.length > 0;
  const accessSummary = allowedDirectory.trim()
    ? `Custom project root: ${allowedDirectory.trim()}`
    : 'No custom root set. The orchestrator will use its safe workspace default.';
  const accessLabel = allowedDirectory.trim()
    ? 'Custom root active'
    : 'Safe default active';

  const handleSendMessage = (message: string) => {
    sendMessage(message, allowedDirectory);
  };

  const handleAllowedDirectoryReset = () => {
    setAllowedDirectory('');
    infoToast('Workspace access reset to the safe default.');
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-[radial-gradient(circle_at_top_left,rgba(76,131,255,0.18),transparent_28%),radial-gradient(circle_at_top_right,rgba(120,227,255,0.12),transparent_24%),linear-gradient(180deg,#070b14_0%,#0a1020_40%,#070b14_100%)] text-white">
      <div className="noise-overlay pointer-events-none absolute inset-0 opacity-40" />

      <div className="relative mx-auto flex min-h-screen max-w-430 flex-col gap-5 px-4 py-4 lg:px-6 lg:py-6">
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_420px]">
          <div className="rounded-[28px] border border-white/10 bg-black/20 p-5 backdrop-blur-xl shadow-[0_18px_60px_rgba(0,0,0,0.22)]">
            <div className="text-[11px] uppercase tracking-[0.3em] text-white/45">
              Workspace
            </div>
            <div className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-white">
              Tarbar AI
            </div>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-white/60">
              A local assistant shell for building, debugging, and exploring
              with live tool feedback. The workspace access control below keeps
              tool calls pinned to the directory you actually want.
            </p>
            <div className="mt-4 flex flex-wrap gap-2 text-xs text-white/55">
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
                Chat + tools
              </span>
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
                Streaming SSE
              </span>
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
                Scoped filesystem access
              </span>
            </div>
          </div>

          <WorkspaceAccessPanel
            allowedDirectory={allowedDirectory}
            defaultDirectory={DEFAULT_ALLOWED_DIRECTORY}
            isStreaming={isStreaming}
            onAllowedDirectoryChange={setAllowedDirectory}
            onReset={handleAllowedDirectoryReset}
          />
        </section>

        <div className="grid min-h-0 gap-5 lg:grid-cols-[320px_minmax(0,1fr)_340px]">
          <aside className="flex flex-col gap-4 rounded-[28px] border border-white/10 bg-black/20 p-4 backdrop-blur-xl lg:sticky lg:top-6 lg:h-[calc(100vh-3rem)]">
            <div className="grid gap-3">
              <SidebarCard
                title="Mode"
                value="Chat + tools"
                description="Stream responses, show tool activity, and keep the interface focused."
              />
              <SidebarCard
                title="Status"
                value={streamStatus.phase}
                description={streamStatus.detail}
              />
              <SidebarCard
                title="Access"
                value={accessLabel}
                description={
                  allowedDirectory.trim()
                    ? 'Tool calls are scoped to the selected project directory.'
                    : "Tool calls fall back to the orchestrator's safe workspace default."
                }
              />
              <SidebarCard
                title="Updated"
                value={lastUpdated}
                description="Reflects the latest assistant event or UI activity."
              />
            </div>

            <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.24em] text-white/45">
                Quick prompts
              </div>
              <div className="mt-3 space-y-2">
                {quickPrompts.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => handleSendMessage(prompt)}
                    disabled={isStreaming}
                    className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-left text-sm leading-6 text-white/80 transition hover:border-sky-300/30 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={clearChat}
              className="mt-auto rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-white/70 transition hover:bg-white/10 hover:text-white"
            >
              Start fresh
            </button>
          </aside>

          <main className="flex min-h-[calc(100vh-2rem)] flex-col overflow-hidden rounded-4xl border border-white/10 bg-[rgba(7,10,18,0.72)] shadow-[0_30px_120px_rgba(0,0,0,0.45)] backdrop-blur-2xl lg:min-h-[calc(100vh-3rem)]">
            <header className="flex flex-col gap-4 border-b border-white/10 px-5 py-5 sm:px-6 lg:px-8">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.3em] text-white/45">
                    Assistant
                  </div>
                  <h1 className="mt-2 text-3xl font-semibold tracking-[-0.05em] text-white sm:text-4xl">
                    Build, ask, and iterate in one place.
                  </h1>
                </div>
                <StatusBadge
                  phase={streamStatus.phase}
                  detail={streamStatus.detail}
                />
              </div>

              <div className="flex flex-wrap gap-2 text-xs text-white/55">
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
                  Local model
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
                  Streaming SSE
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
                  Tool events
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
                  Fast refresh UI
                </span>
              </div>
            </header>

            <div className="flex-1 overflow-y-auto px-3 py-4 sm:px-4 lg:px-6">
              {hasConversation ? (
                <div className="space-y-2">
                  {messages.map((message, index) => (
                    <ChatMessage
                      key={message.id}
                      message={message}
                      isStreaming={isStreaming}
                      isLast={index === messages.length - 1}
                    />
                  ))}
                </div>
              ) : (
                <div className="flex min-h-full items-center justify-center py-10">
                  <EmptyState
                    onSuggestion={(text) => handleSendMessage(text)}
                    accessSummary={accessSummary}
                  />
                </div>
              )}
            </div>

            <div className="border-t border-white/10 bg-black/10 px-3 py-3 sm:px-4 lg:px-6">
              <div className="rounded-[28px] border border-white/10 bg-white/5 p-2 shadow-[0_18px_50px_rgba(0,0,0,0.25)] backdrop-blur-sm">
                <ChatInput
                  onSend={handleSendMessage}
                  onStop={stopStreaming}
                  isStreaming={isStreaming}
                />
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 px-2 text-[11px] text-white/45">
                <span>Current workspace access</span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-white/65">
                  {allowedDirectory.trim() || 'Backend safe default'}
                </span>
              </div>
            </div>
          </main>

          <aside className="flex flex-col gap-4 rounded-[28px] border border-white/10 bg-black/20 p-4 backdrop-blur-xl lg:sticky lg:top-6 lg:h-[calc(100vh-3rem)]">
            <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.24em] text-white/45">
                Activity
              </div>
              <div className="mt-3 space-y-3">
                {activityFeed.length > 0 ? (
                  activityFeed.map((item, index) => (
                    <div
                      key={`${item}-${index}`}
                      className="rounded-2xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-white/70"
                    >
                      {item}
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-white/10 bg-black/10 px-3 py-4 text-sm leading-6 text-white/45">
                    Live events will appear here when the assistant starts
                    thinking or calling tools.
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.24em] text-white/45">
                Tips
              </div>
              <ul className="mt-3 space-y-3 text-sm leading-6 text-white/60">
                <li>
                  Ask for a plan, review, explanation, or implementation help.
                </li>
                <li>Use the quick prompts to seed a new conversation.</li>
                <li>Watch the status badge while the response streams.</li>
              </ul>
            </div>
          </aside>
        </div>
      </div>
      <ToastContainer messages={toasts} onDismiss={removeToast} />
    </div>
  );
}
