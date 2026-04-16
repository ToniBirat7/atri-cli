import { NextRequest } from "next/server";

const LLAMA_URL = process.env.LLAMA_URL || "http://localhost:8080";

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
  role: "user" | "assistant" | "system";
  content: string;
}

export async function POST(req: NextRequest) {
  const { messages }: { messages: Message[] } = await req.json();

  const fullMessages: Message[] = [
    { role: "system", content: SYSTEM_PROMPT },
    ...messages,
  ];

  const response = await fetch(`${LLAMA_URL}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "gemma-4-e2b-it-Q4_K_M.gguf",
      messages: fullMessages,
      stream: true,
      temperature: 1.0,
      top_k: 64,
      top_p: 0.95,
      max_tokens: -1,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    return new Response(JSON.stringify({ error: `llama.cpp error: ${error}` }), {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  const encoder = new TextEncoder();
  const decoder = new TextDecoder();

  const stream = new ReadableStream({
    async start(controller) {
      const reader = response.body!.getReader();

      let buffer = "";

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith("data: ")) continue;

            const data = trimmed.slice(6);
            if (data === "[DONE]") {
              controller.enqueue(encoder.encode("data: [DONE]\n\n"));
              continue;
            }

            try {
              const parsed = JSON.parse(data);
              const content = parsed.choices?.[0]?.delta?.content;
              if (content) {
                controller.enqueue(
                  encoder.encode(`data: ${JSON.stringify({ content })}\n\n`)
                );
              }
            } catch {
              // skip malformed chunks
            }
          }
        }
      } catch (err) {
        controller.enqueue(
          encoder.encode(
            `data: ${JSON.stringify({ error: String(err) })}\n\n`
          )
        );
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
