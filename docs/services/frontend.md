# Frontend Service

The frontend is the browser-facing chat application. It provides the chat UI, the allowed-directory control for filesystem tools, and the prompt-profile selector used to steer orchestrator policy.

## What It Does

The frontend accepts chat input from the user, keeps local chat state, and forwards requests to the Next.js API route. The API route acts as a backend-for-frontend proxy and streams orchestrator SSE events back to the browser.

## Components

### `apps/frontend/src/app/page.tsx`
The main chat screen. It renders:
- the conversation view
- the workspace access selector
- the chat composer and streaming controls

### `apps/frontend/src/lib/useChat.ts`
The browser chat hook. It handles request submission, reads SSE output, appends assistant text, and surfaces errors.

### `apps/frontend/src/app/api/chat/route.ts`
The backend-for-frontend route. It forwards the latest user message, allowed directory, and selected prompt profile to the orchestrator stream endpoint.

## How It Interacts With Other Services

- Sends requests to the orchestrator over HTTP
- Does not talk directly to llama.cpp or MCP servers
- Receives streaming assistant output from the orchestrator and relays it to the browser

## End User Workflow

1. The user types a question in the browser.
2. The user can optionally set an allowed filesystem root.
3. The frontend persists that choice locally and forwards it with each chat request.
4. The frontend submits the request through its API route.
5. The route forwards the request to the orchestrator stream endpoint.
6. The UI renders streamed assistant output as it arrives.

## Deployment Notes

- `NEXT_PUBLIC_API_URL` should point to the orchestrator in deployed environments.
- `NEXT_PUBLIC_PROMPT_PROFILE` provides a default policy when the user does not pick one explicitly.
- The frontend should stay stateless except for local UI state and message history.
