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

export interface UsageCounters {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
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
    case 'usage': {
      const promptTokens = Number(event.prompt_tokens ?? 0);
      const completionTokens = Number(event.completion_tokens ?? 0);
      const totalTokens = Number(event.total_tokens ?? 0);
      return {
        phase: 'thinking',
        detail: `Usage: in ${promptTokens} tok, out ${completionTokens} tok, total ${totalTokens}`,
      };
    }
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
  const [usage, setUsage] = useState<UsageCounters>({
    promptTokens: 0,
    completionTokens: 0,
    totalTokens: 0,
  });
  const abortRef = useRef<AbortController | null>(null);
  const pendingContentRef = useRef('');
  const pendingActivitiesRef = useRef<
    Array<{ line: string; phase: StreamStatus['phase'] }>
  >([]);
  const pendingUsageRef = useRef<UsageCounters>({
    promptTokens: 0,
    completionTokens: 0,
    totalTokens: 0,
  });
  const flushRafRef = useRef<number | null>(null);

  const pushActivity = useCallback(
    (line: string, phase: StreamStatus['phase']) => {
      setStreamStatus({ phase, detail: line });
      setActivityFeed((prev) => [line, ...prev].slice(0, 5));
    },
    [],
  );

  const flushPending = useCallback((assistantMessageId: string) => {
    if (pendingContentRef.current) {
      const chunk = pendingContentRef.current;
      pendingContentRef.current = '';
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMessageId
            ? { ...m, content: m.content + chunk }
            : m,
        ),
      );
    }

    if (
      pendingUsageRef.current.promptTokens > 0 ||
      pendingUsageRef.current.completionTokens > 0 ||
      pendingUsageRef.current.totalTokens > 0
    ) {
      const usageDelta = pendingUsageRef.current;
      pendingUsageRef.current = {
        promptTokens: 0,
        completionTokens: 0,
        totalTokens: 0,
      };
      setUsage((prev) => ({
        promptTokens: prev.promptTokens + usageDelta.promptTokens,
        completionTokens: prev.completionTokens + usageDelta.completionTokens,
        totalTokens: prev.totalTokens + usageDelta.totalTokens,
      }));
    }

    if (pendingActivitiesRef.current.length > 0) {
      const activities = pendingActivitiesRef.current;
      pendingActivitiesRef.current = [];
      const latest = activities[activities.length - 1];
      setStreamStatus({ phase: latest.phase, detail: latest.line });
      setActivityFeed((prev) => {
        const next = [...prev];
        for (let i = activities.length - 1; i >= 0; i -= 1) {
          next.unshift(activities[i].line);
        }
        return next.slice(0, 5);
      });
    }
  }, []);

  const scheduleFlush = useCallback(
    (assistantMessageId: string) => {
      if (flushRafRef.current !== null) {
        return;
      }
      flushRafRef.current = window.requestAnimationFrame(() => {
        flushRafRef.current = null;
        flushPending(assistantMessageId);
      });
    },
    [flushPending],
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
      setUsage({ promptTokens: 0, completionTokens: 0, totalTokens: 0 });
      pendingContentRef.current = '';
      pendingActivitiesRef.current = [];
      pendingUsageRef.current = {
        promptTokens: 0,
        completionTokens: 0,
        totalTokens: 0,
      };

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
                const eventPayload = parsed.event as Record<string, unknown>;
                const eventStatus = describeStreamEvent(eventPayload);
                pendingActivitiesRef.current.push({
                  line: eventStatus.detail,
                  phase: eventStatus.phase,
                });
                if (String(eventPayload.type ?? '') === 'usage') {
                  pendingUsageRef.current.promptTokens += Number(
                    eventPayload.prompt_tokens ?? 0,
                  );
                  pendingUsageRef.current.completionTokens += Number(
                    eventPayload.completion_tokens ?? 0,
                  );
                  pendingUsageRef.current.totalTokens += Number(
                    eventPayload.total_tokens ?? 0,
                  );
                }
                scheduleFlush(assistantMsg.id);
              }
              if (parsed.content) {
                pendingContentRef.current += String(parsed.content);
                scheduleFlush(assistantMsg.id);
              }
              if (parsed.error) {
                if (flushRafRef.current !== null) {
                  window.cancelAnimationFrame(flushRafRef.current);
                  flushRafRef.current = null;
                }
                flushPending(assistantMsg.id);
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
        if (flushRafRef.current !== null) {
          window.cancelAnimationFrame(flushRafRef.current);
          flushRafRef.current = null;
        }
        flushPending(assistantMsg.id);
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
        if (flushRafRef.current !== null) {
          window.cancelAnimationFrame(flushRafRef.current);
          flushRafRef.current = null;
        }
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [messages, flushPending, pushActivity, scheduleFlush],
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
    setUsage({ promptTokens: 0, completionTokens: 0, totalTokens: 0 });
    pendingContentRef.current = '';
    pendingActivitiesRef.current = [];
    pendingUsageRef.current = {
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
    };
    if (flushRafRef.current !== null) {
      window.cancelAnimationFrame(flushRafRef.current);
      flushRafRef.current = null;
    }
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
    usage,
  };
}
