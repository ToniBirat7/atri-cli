'use client';

import { useState, useCallback, useRef } from 'react';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

export interface StreamStatus {
  phase: 'idle' | 'thinking' | 'tool' | 'finalizing' | 'error';
  detail: string;
}

function describeStreamEvent(event: Record<string, unknown>): StreamStatus {
  const type = String(event.type ?? '');
  switch (type) {
    case 'turn_start':
      return {
        phase: 'thinking',
        detail: `Turn ${String(event.turn ?? '')} started`,
      };
    case 'llm_response':
      return {
        phase: 'thinking',
        detail: event.has_content
          ? 'Model responded'
          : 'Model is still reasoning',
      };
    case 'tool_call_start':
      return {
        phase: 'tool',
        detail: `Calling ${String(event.tool_name ?? 'tool')}`,
      };
    case 'tool_call_result':
      return {
        phase: String(event.status ?? '') === 'error' ? 'error' : 'tool',
        detail:
          String(event.status ?? '') === 'error'
            ? `Tool ${String(event.tool_name ?? 'tool')} failed`
            : `Tool ${String(event.tool_name ?? 'tool')} completed`,
      };
    case 'turn_complete':
      return {
        phase: 'thinking',
        detail: `Turn ${String(event.turn ?? '')} complete`,
      };
    case 'turn_final_response':
      return {
        phase: 'finalizing',
        detail: 'Preparing final answer',
      };
    case 'agent_complete':
      return {
        phase: 'idle',
        detail: 'Response complete',
      };
    default:
      return {
        phase: 'thinking',
        detail: type ? `Event: ${type}` : 'Working',
      };
  }
}

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>({
    phase: 'idle',
    detail: 'Ready for a new message',
  });
  const [activityFeed, setActivityFeed] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const pushActivity = useCallback(
    (line: string, phase: StreamStatus['phase']) => {
      setStreamStatus({ phase, detail: line });
      setActivityFeed((prev) => [line, ...prev].slice(0, 5));
    },
    [],
  );

  const sendMessage = useCallback(
    async (
      content: string,
      allowedDirectory?: string,
      promptProfile?: string,
    ) => {
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        content,
        timestamp: Date.now(),
      };

      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: '',
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);

      abortRef.current = new AbortController();

      try {
        // Validate directory if provided
        if (allowedDirectory?.trim()) {
          try {
            const validateRes = await fetch('/api/validate-directory', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: allowedDirectory.trim() }),
              signal: abortRef.current.signal,
            });

            if (!validateRes.ok) {
              const err = await validateRes.json();
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: `Validation Error: ${err.error || 'Failed to validate directory'}`,
                      }
                    : m,
                ),
              );
              setIsStreaming(false);
              pushActivity(
                `Directory validation failed: ${err.message || err.error}`,
                'error',
              );
              return;
            }

            const validation = await validateRes.json();
            if (!validation.ok) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: `Path Error: ${validation.message || validation.error}`,
                      }
                    : m,
                ),
              );
              setIsStreaming(false);
              pushActivity(`Invalid directory: ${validation.message}`, 'error');
              return;
            }

            pushActivity(`Directory validated: ${validation.path}`, 'thinking');
          } catch (validateErr) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsg.id
                  ? {
                      ...m,
                      content: `Validation Error: ${validateErr instanceof Error ? validateErr.message : 'Failed to validate directory'}`,
                    }
                  : m,
              ),
            );
            setIsStreaming(false);
            return;
          }
        }

        const chatHistory = [...messages, userMsg].map((m) => ({
          role: m.role,
          content: m.content,
        }));

        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            messages: chatHistory,
            allowedDirectory: allowedDirectory?.trim() || undefined,
            promptProfile: promptProfile?.trim() || undefined,
          }),
          signal: abortRef.current.signal,
        });

        if (!res.ok) {
          const err = await res.json();
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsg.id
                ? {
                    ...m,
                    content: `Error: ${err.error || 'Failed to connect to llama.cpp server'}`,
                  }
                : m,
            ),
          );
          setIsStreaming(false);
          return;
        }

        const reader = res.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data: ')) continue;

            const data = trimmed.slice(6);
            if (data === '[DONE]') continue;

            try {
              const parsed = JSON.parse(data);
              if (parsed.event) {
                const eventStatus = describeStreamEvent(
                  parsed.event as Record<string, unknown>,
                );
                pushActivity(eventStatus.detail, eventStatus.phase);
              }
              if (parsed.content) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsg.id
                      ? { ...m, content: m.content + parsed.content }
                      : m,
                  ),
                );
              }
              if (parsed.error) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsg.id
                      ? {
                          ...m,
                          content: m.content + `\n\nError: ${parsed.error}`,
                        }
                      : m,
                  ),
                );
                pushActivity(`Error: ${parsed.error}`, 'error');
              }
            } catch {
              // skip
            }
          }
        }
        setStreamStatus({ phase: 'idle', detail: 'Ready for a new message' });
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsg.id
                ? {
                    ...m,
                    content: `Connection error. Is llama-server running on port 8080?`,
                  }
                : m,
            ),
          );
          pushActivity('Connection error while streaming response', 'error');
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [messages],
  );

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
  }, []);

  const clearChat = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setIsStreaming(false);
    setActivityFeed([]);
    setStreamStatus({
      phase: 'idle',
      detail: 'Ready for a new message',
    });
  }, []);

  return {
    messages,
    isStreaming,
    sendMessage,
    stopStreaming,
    clearChat,
    streamStatus,
    activityFeed,
  };
}
