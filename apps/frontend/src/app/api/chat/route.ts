import { NextRequest } from 'next/server';

const ORCHESTRATOR_URL =
  process.env.ORCHESTRATOR_URL || 'http://127.0.0.1:8001';
const PROMPT_PROFILE =
  process.env.NEXT_PUBLIC_PROMPT_PROFILE || 'general-purpose';

interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

interface ChatRequestBody {
  messages: Message[];
  allowedDirectory?: string;
  promptProfile?: string;
}

export async function POST(req: NextRequest) {
  const {
    messages,
    allowedDirectory,
    promptProfile,
  }: ChatRequestBody = await req.json();

  const lastUserMessage = [...messages]
    .reverse()
    .find((m) => m.role === 'user')?.content;

  if (!lastUserMessage) {
    return new Response(JSON.stringify({ error: 'No user message provided' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const orchestratorPayload = {
    message: lastUserMessage,
    allowed_directory: allowedDirectory,
    prompt_profile: promptProfile || PROMPT_PROFILE,
  };

  const response = await fetch(`${ORCHESTRATOR_URL}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(orchestratorPayload),
  });

  if (!response.ok) {
    const error = await response.text();
    return new Response(
      JSON.stringify({ error: `orchestrator error: ${error}` }),
      {
        status: response.status,
        headers: { 'Content-Type': 'application/json' },
      },
    );
  }

  const encoder = new TextEncoder();
  const decoder = new TextDecoder();

  const stream = new ReadableStream({
    async start(controller) {
      try {
        const upstream = response.body?.getReader();
        if (!upstream) {
          throw new Error('Empty stream from orchestrator');
        }

        let buffer = '';
        while (true) {
          const { done, value } = await upstream.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data: ')) continue;
            const data = trimmed.slice(6);

            if (data === '[DONE]') {
              controller.enqueue(encoder.encode('data: [DONE]\n\n'));
              continue;
            }

            try {
              const parsed = JSON.parse(data);
              if (parsed.content) {
                controller.enqueue(
                  encoder.encode(`data: ${JSON.stringify({ content: parsed.content })}\n\n`),
                );
              }
              if (parsed.error) {
                controller.enqueue(
                  encoder.encode(`data: ${JSON.stringify({ error: parsed.error })}\n\n`),
                );
              }
            } catch {
              // Skip malformed chunks and continue streaming.
            }
          }
        }

        controller.enqueue(encoder.encode('data: [DONE]\n\n'));
      } catch (err) {
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify({ error: String(err) })}\n\n`),
        );
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    },
  });
}
