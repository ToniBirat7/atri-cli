import { NextRequest } from 'next/server';

const ORCHESTRATOR_URL =
  process.env.ORCHESTRATOR_URL || 'http://127.0.0.1:8001';

const SYSTEM_PROMPT = `You are "Kanoon Box" (कानून बक्स), Nepal's official AI court information assistant under the UNDP Access to Justice (A2J) Project.

RULES:
- Answer ONLY from the <context> provided in the user message. Never use external knowledge.
- If the context lacks the answer, say: "मलाई यस बारेमा जानकारी उपलब्ध छैन।"
- Match the user's language (Nepali, English, or mixed).
- Use bullet points for clarity. Be complete but concise.
- Never give legal opinions, predict case outcomes, or give case-specific advice.
- End every answer with: "यो जानकारी मार्गदर्शनका लागि मात्र हो, कानूनी सल्लाह होइन।"
- For human help, direct to toll-free: 1660-01-333-55.`;

interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export async function POST(req: NextRequest) {
  const {
    messages,
    allowedDirectory,
  }: { messages: Message[]; allowedDirectory?: string } = await req.json();

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
    message: `${SYSTEM_PROMPT}\n\nUser: ${lastUserMessage}`,
    allowed_directory: allowedDirectory,
  };

  const response = await fetch(`${ORCHESTRATOR_URL}/chat`, {
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

  const json = await response.json();
  const finalText = json?.response || '';

  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      try {
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify({ content: finalText })}\n\n`),
        );
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
