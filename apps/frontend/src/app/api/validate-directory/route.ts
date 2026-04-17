import { NextRequest } from 'next/server';

const ORCHESTRATOR_URL =
  process.env.ORCHESTRATOR_URL || 'http://127.0.0.1:8001';
const ORCHESTRATOR_API_KEY = process.env.ORCHESTRATOR_API_KEY;

interface ValidateDirectoryBody {
  path?: string;
}

export async function POST(req: NextRequest) {
  let body: ValidateDirectoryBody;

  try {
    body = await req.json();
  } catch {
    return new Response(
      JSON.stringify({
        ok: false,
        path: '',
        error: 'Invalid JSON body',
        message: 'Request body must be valid JSON.',
      }),
      {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      },
    );
  }

  const path = body.path?.trim() ?? '';
  if (!path) {
    return new Response(
      JSON.stringify({
        ok: false,
        path: '',
        error: 'Path cannot be empty',
        message: 'Please provide a directory path.',
      }),
      {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      },
    );
  }

  const response = await fetch(`${ORCHESTRATOR_URL}/validate-directory`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(ORCHESTRATOR_API_KEY ? { 'x-api-key': ORCHESTRATOR_API_KEY } : {}),
    },
    body: JSON.stringify({ path }),
  });

  const text = await response.text();
  return new Response(text, {
    status: response.status,
    headers: { 'Content-Type': 'application/json' },
  });
}
