---
paths:
  - "apps/frontend/src/**"
  - "apps/frontend/**/*.tsx"
  - "apps/frontend/**/*.ts"
  - "apps/frontend/**/*.css"
---

# Frontend Rules

## Tech Stack
Next.js 15 App Router · React 19 · TailwindCSS 4 · TypeScript 5 · `react-markdown` + `remark-gfm` + `rehype-highlight`

## Component Patterns
- Components are flat in `apps/frontend/src/components/` — no subdirectory nesting
- All components: PascalCase filename, named export, TypeScript props interface inline
- Example: `ChatMessage.tsx` exports `export default function ChatMessage({ message, isStreaming, isLast }: Props)`
- No component-level test files exist yet

## State Management
- `useChat` hook (`src/lib/useChat.ts`) — all chat state: messages, streaming status, tool activity feed, usage counters
- Component state: `useState` for local UI (allowedDirectory, toast visibility)
- No Redux/Zustand — keep state in hooks and prop-drill; don't add a state library

## Routing
- App Router only — all routes under `apps/frontend/src/app/`
- API proxy routes: `src/app/api/chat/route.ts`, `src/app/api/validate-directory/route.ts`
- Only one page: `src/app/page.tsx` (the main chat UI)

## Data Fetching
- **Streaming:** Frontend calls `POST /api/chat` (Next.js route) → route proxies SSE from orchestrator `/chat/stream`
- Never call the orchestrator directly from browser — always go through the Next.js API route
- `ORCHESTRATOR_URL` is a server-side env var; `NEXT_PUBLIC_API_URL` for client-side (currently unused)
- Allowed directory is stored in `localStorage` key `tarbar.allowedDirectory`

## Styling
- TailwindCSS 4 utility classes only — no custom CSS files, no CSS modules
- Dark glassmorphism design: `bg-black/20`, `backdrop-blur-xl`, `border-white/10`
- Color palette: sky-400 (thinking), amber-400 (tool calls), emerald-400 (finalizing), rose-400 (error)

## Environment Variables
| Variable | Scope | Purpose |
|----------|-------|---------|
| `ORCHESTRATOR_URL` | Server-only | Orchestrator base URL for API routes |
| `ORCHESTRATOR_API_KEY` | Server-only | Auth key sent as `x-api-key` header |
| `NEXT_PUBLIC_API_URL` | Client | Orchestrator URL (currently unused in browser code) |
| `NEXT_PUBLIC_DEFAULT_ALLOWED_DIRECTORY` | Client | Pre-fill workspace directory field |

## SSE Streaming Protocol
The orchestrator emits `data: <JSON>\n\n` events. Event types consumed by `useChat`:
- `session_started` — conversation_id established
- `assistant_delta` — streaming text chunk
- `progress` — tool call in flight (updates activity feed)
- `error` — error event
- `data: [DONE]` — stream complete
